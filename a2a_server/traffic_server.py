# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 交通出行 A2A 服务

通过 A2A JSON-RPC 协议暴露交通智能体，内部经 MCP stdio Client 连接
TrafficMCP（端口 8001），由 LLM 智能路由交通相关工具。

端口：5006（复用 config.A2A_TRAFFIC_PORT）
启动：python -m city_service_assistant.a2a_server.traffic_server
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

# 服务端口：5006（交通 A2A）
SERVER_PORT = config.A2A_TRAFFIC_PORT


class TrafficA2AAgentExecutor(CityA2AAgentExecutor):
    """交通出行领域 A2A 智能体：路由 TrafficMCP 工具。"""

    agent_name = "TrafficAssistant"
    agent_description = "交通出行智能助手：查询城市实时路况、公交地铁换乘、停车场与POI。"
    mcp_module = "city_service_assistant.mcp_server.traffic_server"
    system_prompt = (
        "你是交通出行智能助手。根据用户问题从以下工具中选择合适的工具并给出参数："
        "get_traffic_status(city) 实时路况；get_transit_routes(city,origin,destination) 公交地铁换乘；"
        "get_parking(city,area) 停车场查询；get_poi(city,keywords) POI兴趣点查询。"
        "城市用中文名，如 北京 / 上海 / 广州。"
    )


if __name__ == '__main__':
    run_a2a_server(TrafficA2AAgentExecutor, port=SERVER_PORT)
