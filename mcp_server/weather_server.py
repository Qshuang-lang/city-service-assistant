# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 气象 MCP 服务（FastMCP 协议）

功能：
- get_weather(city)        获取指定城市实时天气（含 3 日趋势匹配）
- get_air_quality(city)    获取指定城市空气质量

数据链路：统一走 data_provider 三级降级（真实API -> api_cache -> 种子表），
返回结果统一附带 data_source 字段标注数据来源。

端口：8002（复用 config.MCP_WEATHER_PORT）
启动：python -m city_service_assistant.mcp_server.weather_server（stdio 传输）
"""

import os
import sys

# 将项目根目录加入 Python 路径，以便导入配置与数据访问层
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from fastmcp import FastMCP

from city_service_assistant.config import config
from city_service_assistant.utils.data_provider import (
    get_weather as _dp_get_weather,
    get_weather_forecast as _dp_get_weather_forecast,
    get_air_quality as _dp_get_air_quality,
)

# 服务端口：8002（气象环境）
SERVER_PORT = config.MCP_WEATHER_PORT

# 创建 FastMCP 服务（stdin/stdout 走 stdio 协议）
mcp = FastMCP(
    "WeatherMCP",
    instructions="气象环境信息服务：查询城市实时天气与空气质量，返回结果含 data_source 数据来源标注。",
)


@mcp.tool(name="get_weather")
def get_weather(city: str) -> dict:
    """
    获取指定城市实时天气（今日单日）

    参数：
        city (str): 城市名，如 北京 / 广州 / 上海

    返回值：
        dict: 今日天气详情，含 data_source 字段标注数据来源（real/cache/simulated）
        如需未来 3 天或多日预报，请使用 get_weather_forecast。
    """
    return _dp_get_weather(city)


@mcp.tool(name="get_weather_forecast")
def get_weather_forecast(city: str, days: int = 3) -> dict:
    """
    获取指定城市未来多日天气预报（默认 3 天，最多 7 天）

    参数：
        city (str): 城市名，如 北京 / 广州 / 上海
        days (int): 预报天数，默认 3，范围 1~7

    返回值：
        dict: {"city", "days": [{fx_date, weather, temp_max, temp_min, humidity, wind_dir, wind_scale, uv_index}, ...], "data_source"}
    """
    return _dp_get_weather_forecast(city, days)


@mcp.tool(name="get_air_quality")
def get_air_quality(city: str) -> dict:
    """
    获取指定城市空气质量

    参数：
        city (str): 城市名，如 北京 / 广州 / 上海

    返回值：
        dict: 空气质量详情（AQI、PM2.5 等），含 data_source 字段标注数据来源
    """
    return _dp_get_air_quality(city)


if __name__ == '__main__':
    # 注意：stdio 传输下 stdout 是 MCP 协议通道，启动日志必须写 stderr，否则污染协议流
    print(f"启动气象 MCP 服务: WeatherMCP（端口 {SERVER_PORT}，stdio 传输）", file=sys.stderr)
    # FastMCP 4.x 推荐 stdio 传输（供 MCP Client / 上层编排层连接）
    mcp.run(transport="stdio")
