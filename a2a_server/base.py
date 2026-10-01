# -*- coding: utf-8 -*-
"""
A2A 层公共基础设施

提供：
1. MCP 工具加载器：通过 MCP stdio Client 连接指定 MCP Server（fastmcp 4.x / mcp 2.x），
   将服务端工具（list_tools -> call_tool）包装为 LangChain BaseTool，供 LLM 智能路由。
   （langchain-mcp-adapters 0.3.x 与 mcp 2.x 不兼容，故自行实现等价封装。）

2. A2A 智能体执行器基类：基于官方 a2a-sdk 的 AgentExecutor 抽象，封装
   「取用户消息 -> LLM 路由 MCP 工具 -> 回填结果 -> 产出 artifacts/完成」的标准流程。

注意：
- MCP Server 均为 stdio 传输（FastMCP 4.x），本层通过 StdioServerParameters 拉起子进程连接。
- MCP 服务端 __main__ 启动日志必须写 stderr（stdout 为协议通道），已在 mcp_server/*.py 中保证。
"""

import asyncio
import json
import os
import sys

# 将项目根目录加入 Python 路径，以便导入配置
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from langchain_core.tools import BaseTool, StructuredTool

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater, InMemoryTaskStore
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.types import (
    TaskState,
    Task,
    TaskStatus,
    Part,
    AgentCard,
    AgentCapabilities,
    AgentInterface,
    AgentSkill,
)

from city_service_assistant.config import config

# 当前 Python 解释器（启动 MCP 子进程用）
_PYTHON = sys.executable
# 项目根目录
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


# ---------------------------------------------------------------------------
# MCP 工具加载：stdio Client -> LangChain BaseTool
# ---------------------------------------------------------------------------
class MCPToolLoader:
    """MCP stdio 客户端工具加载器。

    用法：
        async with MCPToolLoader(module_name) as loader:
            tools = await loader.load_tools()
            result = await loader.call_tool("get_weather", {"city": "北京"})
    """

    def __init__(self, module_name: str, cwd: str = None):
        """
        Args:
            module_name: 待连接的 MCP Server 模块，如
                city_service_assistant.mcp_server.weather_server
            cwd: 子进程工作目录，默认项目根目录（保证 .env / 包导入路径正确）
        """
        self.module_name = module_name
        self.cwd = cwd or _PROJECT_ROOT
        self._session = None
        self._read = None
        self._write = None
        self._client = None

    async def __aenter__(self) -> "MCPToolLoader":
        params = StdioServerParameters(
            command=_PYTHON,
            args=["-m", self.module_name],
            cwd=self.cwd,
            env=None,
        )
        self._client = stdio_client(params)
        self._read, self._write = await self._client.__aenter__()
        self._session = ClientSession(self._read, self._write)
        await self._session.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._session is not None:
            await self._session.__aexit__(exc_type, exc, tb)
            self._session = None
        if self._client is not None:
            await self._client.__aexit__(exc_type, exc, tb)
            self._client = None

    async def list_tools(self):
        """返回 MCP Server 的工具列表（原始 mcp.Tool 对象）。"""
        result = await self._session.list_tools()
        return list(result.tools)

    async def call_tool(self, name: str, arguments: dict) -> str:
        """调用 MCP 工具，返回文本内容（拼接多个 TextContent）。"""
        result = await self._session.call_tool(name, arguments)
        parts = []
        for content in getattr(result, "content", []) or []:
            text = getattr(content, "text", None)
            if text is not None:
                parts.append(text)
        return "\n".join(parts)

    def build_langchain_tools(self, tools) -> list[BaseTool]:
        """将 MCP 原始工具列表包装为 LangChain StructuredTool 列表。"""
        lc_tools = []
        for tool in tools:
            name = tool.name
            description = getattr(tool, "description", "") or name
            input_schema = getattr(tool, "input_schema", None) or {}
            properties = (input_schema.get("properties") or {})

            # 依据 input_schema 的属性生成参数描述（供 LLM 理解入参）
            arg_hints = []
            for prop_name, prop_meta in properties.items():
                ptype = prop_meta.get("type", "string")
                desc = prop_meta.get("description", "")
                required = prop_name in (input_schema.get("required") or [])
                mark = "" if required else "（可选）"
                arg_hints.append(f"{prop_name}({ptype}){mark}: {desc}".strip())

            full_desc = description
            if arg_hints:
                full_desc += "\n参数说明：\n" + "\n".join("- " + h for h in arg_hints)

            async def _run(**kwargs):
                return await self.call_tool(name, kwargs)

            lc_tools.append(
                StructuredTool.from_function(
                    coroutine=_run,
                    name=name,
                    description=full_desc,
                    args_schema=None,  # 由 LLM 依据描述自行填充
                )
            )
        return lc_tools


# ---------------------------------------------------------------------------
# A2A 智能体执行器基类
# ---------------------------------------------------------------------------
class CityA2AAgentExecutor(AgentExecutor):
    """A2A AgentExecutor 基类：封装「LLM 路由 MCP 工具」的通用流程。

    子类需定义：
        agent_name / agent_description / mcp_module
    """

    #: A2A 服务标识（子类覆盖）
    agent_name = "CityAssistant"
    #: A2A 服务能力描述（子类覆盖）
    agent_description = "城市公共服务智能助手"
    #: 需连接的 MCP Server 模块（子类覆盖）
    mcp_module = "city_service_assistant.mcp_server.weather_server"
    #: 系统提示词（子类覆盖）
    system_prompt = "你是城市公共服务智能助手，请根据用户问题选择合适的工具并执行。"

    def __init__(self, llm=None):
        self.llm = llm
        # LLM 懒加载：避免在 import 阶段就校验 API Key
        if self.llm is None:
            from langchain_openai import ChatOpenAI
            self.llm = ChatOpenAI(
                model=config.LLM_MODEL,
                api_key=config.DASHSCOPE_API_KEY,
                base_url=config.LLM_BASE_URL,
                temperature=0,
            )
        self.llm_with_tools = None

    # ------------------------------------------------------------------
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """处理一次 A2A 请求：路由 MCP 工具 -> 产出结果。"""
        task_id = context.task_id
        context_id = context.context_id
        updater = TaskUpdater(event_queue, task_id, context_id)

        # 0. 官方 v1 协议要求：任何状态更新事件之前必须先入队初始 Task 快照
        #    （否则 handler 抛 "Agent should enqueue Task before TaskStatusUpdateEvent"）
        initial_task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
        )
        msg = getattr(context, "message", None)
        if msg is not None:
            initial_task.history.append(msg)
        await event_queue.enqueue_event(initial_task)

        # 1. 标记工作中
        await updater.start_work()

        # 2. 取用户消息文本
        user_text = self._extract_user_text(context)
        if not user_text:
            await updater.requires_input(
                message=updater.new_agent_message(
                    [Part(text="请提供您的查询内容。")]
                )
            )
            return

        # 3. 连接 MCP Server，加载工具
        try:
            async with MCPToolLoader(self.mcp_module) as loader:
                raw_tools = await loader.list_tools()
                lc_tools = loader.build_langchain_tools(raw_tools)
                self.llm_with_tools = self.llm.bind_tools(lc_tools)

                # 4. LLM 智能路由：解析出工具调用
                tool_plan = await self._plan_tools(user_text, lc_tools)

                # 5. 依次执行工具调用，收集结果
                outputs = []
                for call in tool_plan:
                    name = call["name"]
                    args = call.get("args", {}) or {}
                    try:
                        out = await loader.call_tool(name, args)
                    except Exception as e:  # noqa: BLE001
                        out = f"工具 {name} 调用失败: {e}"
                    outputs.append({"tool": name, "args": args, "result": out})

                # 6. 基于工具结果生成最终回答
                answer = await self._finalize(user_text, outputs)

            # 7. 产出结果
            await updater.add_artifact(
                parts=[Part(text=answer, media_type="text/plain")]
            )
            await updater.complete(
                message=updater.new_agent_message(
                    [Part(text=answer, media_type="text/plain")]
                )
            )
        except Exception as e:  # noqa: BLE001 —— 兜底失败状态
            await updater.failed(
                message=updater.new_agent_message(
                    [Part(text=f"处理失败: {e}")]
                )
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """取消任务（基类提供默认实现）。"""
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_user_text(context: RequestContext) -> str:
        """从请求上下文中提取用户文本。"""
        try:
            message = context.message
            parts = list(getattr(message, "parts", []) or [])
            texts = []
            for part in parts:
                # protobuf Part 的 text 字段（oneof content 下）
                try:
                    t = part.text
                except Exception:  # noqa: BLE001
                    t = None
                if t:
                    texts.append(t)
            return "\n".join(texts).strip()
        except Exception:  # noqa: BLE001
            return ""

    async def _plan_tools(self, user_text: str, tools: list[BaseTool]) -> list[dict]:
        """让 LLM 决定调用哪些工具及参数，返回 [{'name','args'}, ...]。

        若 LLM 未产生工具调用，则直接以原始文本作为一次「无工具」计划，
        由 _finalize 兜底生成回答。
        """
        try:
            if self.llm_with_tools is None:
                self.llm_with_tools = self.llm.bind_tools(tools)
            resp = await self.llm_with_tools.ainvoke(
                [
                    ("system", self.system_prompt),
                    ("human", user_text),
                ]
            )
            calls = getattr(resp, "tool_calls", None) or []
            plan = []
            for c in calls:
                name = c.get("name", "")
                args = c.get("args", {}) or {}
                if name:
                    plan.append({"name": name, "args": args})
            return plan
        except Exception:  # noqa: BLE001
            return []

    async def _finalize(self, user_text: str, outputs: list[dict]) -> str:
        """基于工具执行结果生成最终回答文本。"""
        if not outputs:
            return "抱歉，我未能解析出可用的查询工具，请补充更多信息后重试。"

        lines = [f"用户问题：{user_text}", ""]
        for item in outputs:
            lines.append(f"【{item['tool']}】")
            try:
                result_obj = json.loads(item["result"]) if item["result"] else {}
                if isinstance(result_obj, dict) and "data_source" in result_obj:
                    src = result_obj.pop("data_source")
                    lines.append(json.dumps(result_obj, ensure_ascii=False, indent=2))
                    lines.append(f"（数据来源：{src}）")
                else:
                    lines.append(item["result"])
            except Exception:  # noqa: BLE001 —— 非 JSON 结果原样输出
                lines.append(item["result"])
            lines.append("")
        return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# A2A 应用组装
# ---------------------------------------------------------------------------
def build_a2a_app(executor: CityA2AAgentExecutor, port: int, version: str = "1.0.0"):
    """组装官方 a2a-sdk 服务：AgentCard + RequestHandler + 路由 -> ASGI App。

    Args:
        executor: 已配置好 mcp_module 的 A2A AgentExecutor 实例
        port: 本服务监听端口（用于 AgentCard.supported_interfaces）
        version: AgentCard 版本号

    Returns:
        (app, public_agent_card)：Starlette 应用与公开 AgentCard
    """
    skill = AgentSkill(
        id=executor.agent_name,
        name=executor.agent_name,
        description=executor.agent_description,
        input_modes=["text/plain"],
        output_modes=["text/plain"],
        tags=["city-service", "a2a"],
        examples=["查询北京实时天气", "北京今天路况如何"],
    )

    public_agent_card = AgentCard(
        name=executor.agent_name,
        description=executor.agent_description,
        version=version,
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=f"http://127.0.0.1:{port}",
                protocol_version="1.0",
            )
        ],
        skills=[skill],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=public_agent_card,
    )

    routes = []
    routes.extend(create_agent_card_routes(public_agent_card))
    routes.extend(create_jsonrpc_routes(request_handler, "/"))

    from starlette.applications import Starlette
    app = Starlette(routes=routes)
    return app, public_agent_card


def run_a2a_server(executor_cls, port: int, host: str = "127.0.0.1", version: str = "1.0.0"):
    """启动 A2A 服务（uvicorn 运行 Starlette App）。"""
    import uvicorn

    executor = executor_cls()
    app, card = build_a2a_app(executor, port, version=version)
    print(f"启动 A2A 服务: {card.name}（端口 {port}，JSONRPC 传输）", file=sys.stderr)
    print(f"  AgentCard: http://{host}:{port}/.well-known/agent-card.json", file=sys.stderr)
    print(f"  连接 MCP Server: {executor_cls.mcp_module}", file=sys.stderr)
    uvicorn.run(app, host=host, port=port, log_level="info")
