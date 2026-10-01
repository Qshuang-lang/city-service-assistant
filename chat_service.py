# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 主路由服务（ChatService）

同构复刻 SmartVoyage 参考项目 chat_service.py，实现主助手层完整对话编排：
    用户输入 → 意图识别(intent_agent) → 启发式路由(_should_skip_planning)
            → [直接执行 / Planning+ReAct(planning_agent → react_loop)] → 回复

关键差异（业务域适配 + 技术栈统一）：
1. 意图集替换为城市公共服务三类：气象环境 / 交通出行 / 生活政务，
   分别路由到三个 A2A 子代理（WeatherEnvAssistant:5005 / TrafficAssistant:5006 / LifeServiceAssistant:5007），
   agent 名称与端口取自 config.INTENT_AGENT_MAP 与 config.A2A_*_PORT。
2. 子代理调用方式：使用官方 a2a-sdk 的 create_client + httpx 长超时 ClientConfig
   （与 scripts/a2a_smoke.py 已验证的调用方式一致），逐条流式读取任务 artifact。
3. 记忆持久化复用 city_service_assistant.memory.ConversationMemory（基于 db.py）。

架构：
    api_server(FastAPI:8080) / main(CLI)
        └── ChatService
              ├── llm (ChatOpenAI) —— 意图识别 / 规划 / 结果总结
              ├── memory (ConversationMemory) —— 短时对话 / 画像 / 任务上下文 / 实体历史
              └── a2a 客户端 —— 调用 3 个子代理
"""
import asyncio
import json
import re
import uuid
from collections import OrderedDict
from datetime import datetime

import pytz
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from city_service_assistant.config import config
from city_service_assistant.create_logger import logger
from city_service_assistant.main_prompts import CityServicePrompts
from city_service_assistant.memory import ConversationMemory


# 子代理元信息（AgentCard 静态描述；skills 用于 /api/agents 展示）
AGENT_META = {
    "WeatherEnvAssistant": {
        "description": "气象环境子代理：实时天气、空气质量、气象灾害预警",
        "skills": ["天气查询: 根据城市查询实时天气/预报", "空气质量: 查询城市空气质量指数",
                   "气象预警: 查询气象灾害预警信息"],
    },
    "TrafficAssistant": {
        "description": "交通出行子代理：实时路况、公共交通、地理编码、停车信息",
        "skills": ["实时路况: 查询路段/区域拥堵状态", "公共交通: 公交地铁线路与换乘",
                   "地理编码: 地址与坐标互转", "停车: 停车场查询"],
    },
    "LifeServiceAssistant": {
        "description": "生活政务子代理：POI检索、办事指南、投诉建议",
        "skills": ["POI检索: 地点/周边服务检索", "办事指南: 政务办事流程指引",
                   "投诉建议: 记录并反馈投诉建议"],
    },
}


class ChatService:
    """
    城市公共服务智能助手核心对话服务
    """

    def __init__(self):
        # ========== 1. A2A 子代理地址映射 ==========
        self.agent_urls = {
            "WeatherEnvAssistant": f"http://127.0.0.1:{config.A2A_WEATHER_PORT}",
            "TrafficAssistant": f"http://127.0.0.1:{config.A2A_TRAFFIC_PORT}",
            "LifeServiceAssistant": f"http://127.0.0.1:{config.A2A_LIFE_PORT}",
        }

        # ========== 2. 大模型（意图识别 / 规划 / 总结） ==========
        self.llm = ChatOpenAI(
            model=config.LLM_MODEL,
            api_key=config.DASHSCOPE_API_KEY,
            base_url=config.LLM_BASE_URL,
            temperature=0.1,
        )

        # ========== 3. 记忆与对话状态 ==========
        self.memory = ConversationMemory(short_term_limit=10)
        self.messages = []               # [{"role": "user/assistant", "content": "..."}]
        self.conversation_history = ""   # 完整对话历史字符串
        self._available_tools_text = ""  # 工具列表缓存

        # ========== 4. 从数据库加载持久化记忆 ==========
        self._init_db_and_load_memory()

    # ==================== 初始化 ====================

    def _init_db_and_load_memory(self):
        """从 MySQL 恢复用户画像 / 实体历史 / 短期对话"""
        try:
            self.memory.load_profile_from_db()
            self.memory.load_entities_from_db()
            self.memory.load_messages_from_db()
            for msg in self.memory.short_term_messages:
                self.messages.append({"role": msg["role"], "content": msg["content"]})
            logger.info(
                "记忆加载完成: 画像=%d项, 历史=%d条, 对话=%d条",
                len(self.memory.user_profile), len(self.memory.entity_history),
                len(self.memory.short_term_messages),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("数据库记忆加载失败（将使用纯内存模式）: %s", e)

    # ==================== 意图识别 ====================

    def intent_agent(self, user_input: str):
        """
        意图识别：分析用户输入，输出意图列表 / 改写查询 / 追问消息
        返回: (intents, user_queries, follow_up_message)
        """
        chain = CityServicePrompts.intent_prompt() | self.llm
        current_date = datetime.now(pytz.timezone("Asia/Shanghai")).strftime("%Y-%m-%d")

        intent_response = chain.invoke({
            "conversation_history": self.memory.get_short_term_text(),
            "query": user_input,
            "current_date": current_date,
            "user_profile": self.memory.get_profile_text(),
            "task_context": json.dumps(self.memory.current_task, ensure_ascii=False),
        }).content.strip()
        logger.info("意图识别原始响应: %s", intent_response)

        # 去掉 ```json ... ``` 代码块标记
        intent_response = re.sub(r"^```json\s*|\s*```$", "", intent_response).strip()
        intent_output = json.loads(intent_response)
        intents = intent_output.get("intents", [])
        user_queries = intent_output.get("user_queries", {})
        follow_up_message = intent_output.get("follow_up_message", "")
        logger.info("intents=%s || user_queries=%s || follow_up=%s",
                    intents, user_queries, follow_up_message)
        return intents, user_queries, follow_up_message

    # ==================== 启发式路由 ====================

    def _should_skip_planning(self, intents: list) -> bool:
        """
        启发式判断是否跳过 planning_agent（省 1 次 LLM 调用）：
        1. 单意图 → 跳过
        2. 多意图但全部为独立查询类意图（config.INDEPENDENT_INTENTS）→ 跳过
        """
        if len(intents) <= 1:
            return True
        for intent in intents:
            if intent not in config.INDEPENDENT_INTENTS:
                # 含 complex / 需分步的意图 → 进入规划
                return False
        return True

    # ==================== 任务规划 ====================

    def planning_agent(self, intents: list, user_queries: dict) -> dict:
        """任务规划：LLM 生成执行计划（复杂任务才进入）"""
        chain = CityServicePrompts.planning_prompt() | self.llm
        planning_response = chain.invoke({
            "conversation_history": self.memory.get_short_term_text(),
            "query": self.messages[-1]["content"] if self.messages else "",
            "intents": json.dumps(intents, ensure_ascii=False),
            "user_queries": json.dumps(user_queries, ensure_ascii=False),
        }).content.strip()
        logger.info("规划响应: %s", planning_response)

        planning_response = re.sub(r"^```json\s*|\s*```$", "", planning_response).strip()
        return json.loads(planning_response)

    # ==================== A2A 子代理调用 ====================

    async def _a2a_send(self, agent_name: str, text: str) -> str:
        """
        通过官方 a2a-sdk 调用子代理（create_client + httpx 长超时 ClientConfig）

        与 scripts/a2a_smoke.py 保持一致：SendMessage 流式读取任务 artifact。
        返回子代理最终回复文本；异常时返回友好错误信息。
        """
        url = self.agent_urls.get(agent_name)
        if not url:
            return f"抱歉，{agent_name} 未配置地址。"
        try:
            import httpx
            from a2a.client import ClientConfig, create_client
            from a2a.types.a2a_pb2 import Message as PbMsg
            from a2a.types.a2a_pb2 import SendMessageRequest as PbReq

            # httpx 长超时：规避子代理 LLM+MCP 调用链耗时导致客户端超时
            http_client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0), trust_env=False)
            cfg = ClientConfig(httpx_client=http_client)
            try:
                async with await create_client(url, client_config=cfg) as client:
                    msg = PbMsg(
                        message_id="msg-" + uuid.uuid4().hex[:12],
                        role=1,  # ROLE_USER
                        parts=[{"text": text}],
                    )
                    req = PbReq(message=msg)
                    collected = []
                    failed_msg = ""
                    async for resp in client.send_message(req):
                        task = getattr(resp, "task", None)
                        if task is None and hasattr(resp, "result"):
                            task = resp.result
                        if task is None:
                            continue
                        for art in (getattr(task, "artifacts", None) or []):
                            for part in (getattr(art, "parts", None) or []):
                                t = getattr(part, "text", None) or ""
                                if t:
                                    collected.append(t)
                        status = getattr(task, "status", None)
                        state = getattr(status, "state", None)
                        if state in ("failed", "error", "input-required") and not collected:
                            sm = getattr(status, "message", None)
                            if sm is not None:
                                failed_msg = "".join(
                                    getattr(p, "text", None) or "" for p in (getattr(sm, "parts", None) or [])
                                )
                    if collected:
                        return "".join(collected)
                    if failed_msg:
                        return f"查询失败：{failed_msg}"
                    return "查询失败：子代理未返回有效结果"
            finally:
                await http_client.aclose()
        except Exception as e:  # noqa: BLE001
            logger.error("%s 调用异常: %s", agent_name, e)
            return f"{agent_name} 服务暂时不可用：{e}"

    async def _call_agent_intent(self, intent: str, query_str: str) -> str:
        """
        统一调用子代理并总结结果（简单任务直接执行 & ReAct 步骤共用）
        """
        agent_name = config.INTENT_AGENT_MAP.get(intent)
        if not agent_name:
            return "暂不支持此意图。"

        # 更新任务上下文，调用后把结果写入实体历史（含 response）
        self.memory.update_task_context({"type": intent, "query": query_str})
        agent_input = json.dumps({
            "history": self.memory.get_short_term_text(),
            "query": query_str,
        }, ensure_ascii=False)
        agent_result = await self._a2a_send(agent_name, agent_input)
        self.memory.extract_entities(intent, query_str, agent_result)

        # 按子代理类型做结果总结
        if agent_name == "WeatherEnvAssistant":
            chain = CityServicePrompts.summarize_weather_prompt() | self.llm
            return chain.invoke({"query": query_str, "raw_response": agent_result}).content.strip()
        if agent_name == "TrafficAssistant":
            chain = CityServicePrompts.summarize_traffic_prompt() | self.llm
            return chain.invoke({"query": query_str, "raw_response": agent_result}).content.strip()
        if agent_name == "LifeServiceAssistant":
            chain = CityServicePrompts.summarize_life_prompt() | self.llm
            return chain.invoke({"query": query_str, "raw_response": agent_result}).content.strip()
        return agent_result

    # ==================== ReAct 循环 ====================

    async def execute_step(self, step: dict, user_queries: dict) -> str:
        """执行单个计划步骤（Action），委托给统一 agent 调用"""
        intent = step.get("intent", "")
        query_str = user_queries.get(intent, self.messages[-1]["content"] if self.messages else "")
        logger.info("执行步骤: %s，意图: %s", step.get("action", ""), intent)
        return await self._call_agent_intent(intent, query_str)

    async def react_loop(self, steps: list, user_queries: dict) -> str:
        """
        ReAct 循环：按 depends_on 分组，组内并行执行 Action（跳过 Thought），
        最后用 LLM 汇总所有 Observation 生成连贯回复。
        """
        observations = []
        step_results = []

        dep_groups = OrderedDict()
        for step in steps:
            dep_groups.setdefault(step.get("depends_on", 0), []).append(step)

        for dep_key, group_steps in dep_groups.items():  # noqa: BLE001
            if len(group_steps) > 1:
                logger.info("并行执行 %d 个无依赖步骤", len(group_steps))
                results = await asyncio.gather(
                    *(self.execute_step(s, user_queries) for s in group_steps),
                    return_exceptions=True,
                )
                for step, result in zip(group_steps, results):
                    step_num = step.get("step", 0)
                    step_desc = step.get("description", step.get("action", ""))
                    if isinstance(result, Exception):
                        result = f"执行失败：{result}"
                    observations.append(result)
                    step_results.append({"step": step_num, "description": step_desc, "result": result})
                    logger.info("ReAct 步骤 %s 结果: %s", step_num, str(result)[:100])
            else:
                step = group_steps[0]
                step_num = step.get("step", 0)
                step_desc = step.get("description", step.get("action", ""))
                result = await self.execute_step(step, user_queries)
                observations.append(result)
                step_results.append({"step": step_num, "description": step_desc, "result": result})
                logger.info("ReAct 步骤 %s 结果: %s", step_num, str(result)[:100])

        if len(step_results) > 1:
            summary_chain = CityServicePrompts.react_summary_prompt() | self.llm
            all_obs = "\n".join(
                f"步骤{s['step']} ({s['description']}): {s['result']}" for s in step_results
            )
            return summary_chain.invoke({
                "query": self.messages[-1]["content"] if self.messages else "",
                "all_observations": all_obs,
            }).content.strip()

        return observations[0] if observations else "暂无结果"

    # ==================== 对话主方法 ====================

    async def chat(self, user_input: str) -> str:
        """
        对话主方法：写入记忆 → 意图识别 → 特殊情况 → 规划(启发式) → 执行 → 写回记忆
        """
        self.memory.add_message("user", user_input)
        self.messages.append({"role": "user", "content": user_input})
        self.conversation_history += f"\nUser: {user_input}"

        try:
            # 1. 意图识别
            intents, user_queries, follow_up_message = self.intent_agent(user_input)

            # 2. 特殊情况
            if "out_of_scope" in intents:
                response = follow_up_message
            elif follow_up_message != "":
                response = follow_up_message
            else:
                # 3. 启发式路由：简单任务跳过规划
                if self._should_skip_planning(intents):
                    plan = {"need_plan": False, "reason": "启发式判断：任务简单，可直接执行", "steps": []}
                    logger.info("跳过规划: %s", plan["reason"])
                else:
                    plan = self.planning_agent(intents, user_queries)
                need_plan = plan.get("need_plan", False)
                logger.info("规划结果: need_plan=%s, reason=%s", need_plan, plan.get("reason", ""))

                if need_plan:
                    # 4a. Planning + ReAct：复杂任务
                    response = await self.react_loop(plan.get("steps", []), user_queries)
                else:
                    # 4b. 直接执行：遍历意图依次调用子代理
                    responses = []
                    routed_agents = []
                    for intent in intents:
                        logger.info("处理意图: %s", intent)
                        query_str = user_queries.get(intent, "")
                        result = await self._call_agent_intent(intent, query_str)
                        responses.append(result)
                        agent = config.INTENT_AGENT_MAP.get(intent)
                        if agent:
                            routed_agents.append(agent)
                    response = "\n\n".join(responses)
                    if routed_agents:
                        logger.info("路由到代理: %s", routed_agents)

            # 5. 写回记忆
            self.memory.add_message("assistant", response)
            self.conversation_history += f"\nAssistant: {response}"
            self.messages.append({"role": "assistant", "content": response})
            return response

        except json.JSONDecodeError as e:
            logger.error("意图识别 JSON 解析失败: %s", e)
            error_message = f"意图识别 JSON 解析失败：{str(e)}。请重试。"
            self.memory.add_message("assistant", error_message)
            self.messages.append({"role": "assistant", "content": error_message})
            return error_message
        except Exception as e:  # noqa: BLE001
            logger.error("处理异常: %s", e)
            error_message = f"处理失败：{str(e)}。请重试。"
            self.memory.add_message("assistant", error_message)
            self.messages.append({"role": "assistant", "content": error_message})
            return error_message

    # ==================== 流式对话 ====================

    async def _call_agent_intent_stream(self, intent: str, query_str: str):
        """流式版本：子代理结果 → LLM 总结 → astream 逐 chunk yield"""
        agent_name = config.INTENT_AGENT_MAP.get(intent)
        if not agent_name:
            yield "暂不支持此意图。"
            return

        self.memory.update_task_context({"type": intent, "query": query_str})
        agent_input = json.dumps({
            "history": self.memory.get_short_term_text() + f"\nUser: {query_str}",
            "query": query_str,
        }, ensure_ascii=False)
        agent_result = await self._a2a_send(agent_name, agent_input)
        self.memory.extract_entities(intent, query_str, agent_result)

        summarize = {
            "WeatherEnvAssistant": CityServicePrompts.summarize_weather_prompt(),
            "TrafficAssistant": CityServicePrompts.summarize_traffic_prompt(),
            "LifeServiceAssistant": CityServicePrompts.summarize_life_prompt(),
        }.get(agent_name)
        if summarize is None:
            yield agent_result
            return

        chain = summarize | self.llm
        async for chunk in chain.astream({"query": query_str, "raw_response": agent_result}):
            yield chunk.content if hasattr(chunk, "content") else str(chunk)

    async def _react_loop_stream(self, steps: list, user_queries: dict):
        """流式版本 ReAct 循环：Action 同 react_loop，最终汇总 astream"""
        observations = []
        step_results = []

        dep_groups = OrderedDict()
        for step in steps:
            dep_groups.setdefault(step.get("depends_on", 0), []).append(step)

        for dep_key, group_steps in dep_groups.items():  # noqa: BLE001
            if len(group_steps) > 1:
                logger.info("并行执行 %d 个无依赖步骤(stream)", len(group_steps))
                results = await asyncio.gather(
                    *(self.execute_step(s, user_queries) for s in group_steps),
                    return_exceptions=True,
                )
                for step, result in zip(group_steps, results):
                    step_num = step.get("step", 0)
                    step_desc = step.get("description", step.get("action", ""))
                    if isinstance(result, Exception):
                        result = f"执行失败：{result}"
                    observations.append(result)
                    step_results.append({"step": step_num, "description": step_desc, "result": result})
            else:
                step = group_steps[0]
                step_num = step.get("step", 0)
                step_desc = step.get("description", step.get("action", ""))
                result = await self.execute_step(step, user_queries)
                observations.append(result)
                step_results.append({"step": step_num, "description": step_desc, "result": result})

        if len(step_results) > 1:
            summary_chain = CityServicePrompts.react_summary_prompt() | self.llm
            all_obs = "\n".join(
                f"步骤{s['step']} ({s['description']}): {s['result']}" for s in step_results
            )
            async for chunk in summary_chain.astream({
                "query": self.messages[-1]["content"] if self.messages else "",
                "all_observations": all_obs,
            }):
                yield chunk.content if hasattr(chunk, "content") else str(chunk)
        else:
            yield observations[0] if observations else "暂无结果"

    async def chat_stream(self, user_input: str):
        """
        流式对话主方法：与 chat 流程一致，最终回复逐 chunk yield（供 SSE 使用）
        """
        self.memory.add_message("user", user_input)
        self.messages.append({"role": "user", "content": user_input})
        self.conversation_history += f"\nUser: {user_input}"

        try:
            intents, user_queries, follow_up_message = self.intent_agent(user_input)

            if "out_of_scope" in intents or follow_up_message != "":
                response = follow_up_message
                yield response
            else:
                if self._should_skip_planning(intents):
                    plan = {"need_plan": False, "reason": "启发式判断：任务简单，可直接执行", "steps": []}
                    logger.info("跳过规划(stream): %s", plan["reason"])
                else:
                    plan = self.planning_agent(intents, user_queries)
                need_plan = plan.get("need_plan", False)

                if need_plan:
                    parts = []
                    async for chunk in self._react_loop_stream(plan.get("steps", []), user_queries):
                        parts.append(chunk)
                        yield chunk
                    response = "".join(parts)
                else:
                    responses = []
                    for intent in intents:
                        logger.info("处理意图(stream): %s", intent)
                        query_str = user_queries.get(intent, "")
                        parts = []
                        async for chunk in self._call_agent_intent_stream(intent, query_str):
                            parts.append(chunk)
                            yield chunk
                        responses.append("".join(parts))
                    response = "\n\n".join(responses)

            self.memory.add_message("assistant", response)
            self.conversation_history += f"\nAssistant: {response}"
            self.messages.append({"role": "assistant", "content": response})

        except json.JSONDecodeError as e:
            logger.error("意图识别 JSON 解析失败(stream): %s", e)
            error_message = f"意图识别 JSON 解析失败：{str(e)}。请重试。"
            yield error_message
        except Exception as e:  # noqa: BLE001
            logger.error("处理异常(stream): %s", e)
            error_message = f"处理失败：{str(e)}。请重试。"
            yield error_message

    # ==================== 工具 / 卡片 / 记忆管理 ====================

    def get_agent_cards(self) -> list:
        """获取三个 A2A 子代理的卡片信息"""
        cards = []
        for agent_name, meta in AGENT_META.items():
            cards.append({
                "name": agent_name,
                "description": meta["description"],
                "skills": meta["skills"],
                "url": self.agent_urls.get(agent_name, "未知地址"),
                "status": "在线",
            })
        return cards

    def get_memory_state(self) -> dict:
        """记忆状态摘要（供 /api/memory）"""
        return {
            "short_term_messages": [
                {"role": "用户" if m["role"] == "user" else "助手",
                 "content": m["content"], "timestamp": m["timestamp"]}
                for m in self.memory.short_term_messages[-5:]
            ],
            "user_profile": self.memory.user_profile,
            "current_task": self.memory.current_task,
            "entity_history": self.memory.entity_history[-5:],
        }

    def update_user_profile(self, profile: dict):
        """更新用户画像（由 /api/memory/profile 调用）"""
        self.memory.update_profile(profile)
        logger.info("更新用户画像: %s", profile)

    def clear_memory(self):
        """清空全部记忆（内存 + 数据库）"""
        self.memory.clear()
        self.messages.clear()
        self.conversation_history = ""
        logger.info("已清空全部记忆")
