# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 生活政务 A2A 服务

通过 A2A JSON-RPC 协议暴露生活政务智能体，内部经 MCP stdio Client 连接
LifeMCP（端口 8003），由 LLM 智能路由服务指南相关工具。

端口：5007（复用 config.A2A_LIFE_PORT）
启动：python -m city_service_assistant.a2a_server.life_server
"""

import os
import sys

# 将项目根目录加入 Python 路径，以便导入配置
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from city_service_assistant.config import config
from city_service_assistant.a2a_server.base import (
    CityA2AAgentExecutor,
    run_a2a_server,
)

# 服务端口：5007（生活政务 A2A）
SERVER_PORT = config.A2A_LIFE_PORT


class LifeA2AAgentExecutor(CityA2AAgentExecutor):
    """生活政务领域 A2A 智能体：路由 LifeMCP 工具。"""

    agent_name = "LifeServiceAssistant"
    agent_description = "生活政务智能助手：查询便民服务指南与检索政务办事指南。"
    mcp_module = "city_service_assistant.mcp_server.life_server"
    system_prompt = (
        "你是生活政务智能助手。根据用户问题从以下工具中选择合适的工具并给出参数："
        "get_service_guide(service_name) 查询具体服务指南；"
        "search_guides(keywords) 全文检索政务办事指南（语义搜索）。"
        "请用中文简洁回答用户。"
    )


if __name__ == '__main__':
    run_a2a_server(LifeA2AAgentExecutor, port=SERVER_PORT)
