# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - A2A 服务包

A2A（Agent-to-Agent）协议层：为每个领域 MCP 服务提供一个 A2A 智能体端点，
供上层编排 / 其它 Agent 通过标准 A2A JSON-RPC 协议调用。

三个 A2A 服务（官方 a2a-sdk，HTTP JSON-RPC 传输，uvicorn 启动）：
- weather_server.py   气象 A2A 服务（端口 5005，连接 WeatherMCP 8002）
- traffic_server.py   交通 A2A 服务（端口 5006，连接 TrafficMCP 8001）
- life_server.py      生活政务 A2A 服务（端口 5007，连接 LifeMCP 8003）

每个 A2A 服务内部通过 MCP stdio Client 连接对应 MCP Server，
将 MCP 工具包装为 LangChain 工具后由 LLM 智能路由执行，实现
「A2A 层 -> MCP 层 -> 数据层」的完整链路。

启动方式（分别启动三个进程）：
    python -m city_service_assistant.a2a_server.weather_server
    python -m city_service_assistant.a2a_server.traffic_server
    python -m city_service_assistant.a2a_server.life_server
"""
