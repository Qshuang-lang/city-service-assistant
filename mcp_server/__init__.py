# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - MCP 服务包

三个 FastMCP 服务（stdio 传输），统一复用 config 端口常量：
- weather_server.py   气象 MCP 服务（端口 8002）：get_weather / get_air_quality
- traffic_server.py   交通 MCP 服务（端口 8001）：get_traffic_status / get_transit_routes / get_parking / get_poi
- life_server.py      生活政务 MCP 服务（端口 8003）：get_service_guide / search_guides(RAG)

启动方式（分别启动三个进程）：
    python -m city_service_assistant.mcp_server.weather_server
    python -m city_service_assistant.mcp_server.traffic_server
    python -m city_service_assistant.mcp_server.life_server
"""
