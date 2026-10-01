# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 气象 A2A 服务

通过 A2A JSON-RPC 协议暴露气象智能体，内部经 MCP stdio Client 连接
WeatherMCP（端口 8002），由 LLM 智能路由 get_weather / get_air_quality 工具。

端口：5005（复用 config.A2A_WEATHER_PORT）
启动：python -m city_service_assistant.a2a_server.weather_server
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

# 服务端口：5005（气象 A2A）
SERVER_PORT = config.A2A_WEATHER_PORT


class WeatherA2AAgentExecutor(CityA2AAgentExecutor):
    """气象领域 A2A 智能体：路由 WeatherMCP 工具。"""

    agent_name = "WeatherEnvAssistant"
    agent_description = "气象环境智能助手：查询城市实时天气与空气质量。"
    mcp_module = "city_service_assistant.mcp_server.weather_server"
    system_prompt = (
        "你是气象环境智能助手。根据用户问题从以下工具中选择合适的工具并给出参数："
        "get_weather(city) 获取城市今日实时天气；"
        "get_weather_forecast(city, days=3) 获取未来多日天气预报（近三日/未来几天天气用此工具）；"
        "get_air_quality(city) 获取城市空气质量。"
        "城市名用中文，如 北京 / 上海 / 广州。"
        "用户问'近几天/未来几天/周末天气'等多日场景，务必调用 get_weather_forecast 一次返回多日，"
        "不要用 get_weather 单日结果硬凑。"
    )


if __name__ == '__main__':
    run_a2a_server(WeatherA2AAgentExecutor, port=SERVER_PORT)
