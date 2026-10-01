# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 交通 MCP 服务（FastMCP 协议）

功能：
- get_traffic_status(city)   获取城市实时路况
- get_transit_routes(city)   获取城市公交/地铁线路
- get_parking(city)          获取城市停车场
- get_poi(city, poi_type)    获取公共设施 POI（医院/图书馆/公园/政务大厅等）

数据链路：统一走 data_provider 三级降级（真实API -> api_cache -> 种子表），
返回结果统一附带 data_source 字段标注数据来源。

端口：8001（复用 config.MCP_TRAFFIC_PORT）
启动：python -m city_service_assistant.mcp_server.traffic_server（stdio 传输）
"""

import os
import sys

# 将项目根目录加入 Python 路径，以便导入配置与数据访问层
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from fastmcp import FastMCP

from city_service_assistant.config import config
from city_service_assistant.utils.data_provider import (
    get_traffic_status as _dp_get_traffic_status,
    get_transit_routes as _dp_get_transit_routes,
    get_parking as _dp_get_parking,
    get_poi as _dp_get_poi,
)

# 服务端口：8001（交通出行）
SERVER_PORT = config.MCP_TRAFFIC_PORT

# 创建 FastMCP 服务（stdin/stdout 走 stdio 协议）
mcp = FastMCP(
    "TrafficMCP",
    instructions="交通出行信息服务：查询实时路况、公交地铁线路、停车场、公共设施 POI，返回结果含 data_source 数据来源标注。",
)


@mcp.tool(name="get_traffic_status")
def get_traffic_status(city: str) -> dict:
    """
    获取城市实时路况

    参数：
        city (str): 城市名，如 北京 / 广州 / 上海

    返回值：
        dict: 路况列表（roads），含 data_source 字段标注数据来源
    """
    return _dp_get_traffic_status(city)


@mcp.tool(name="get_transit_routes")
def get_transit_routes(city: str, origin: str = None, destination: str = None) -> dict:
    """
    查询城市公交/地铁线路，或点对点换乘方案

    参数：
        city (str): 城市名，如 北京 / 上海 / 广州
        origin (str, 可选): 起点位置/站点，如 北京西站
        destination (str, 可选): 终点位置/站点，如 首都机场T3

    返回值：
        dict: 未提供起终点时返回线路列表（routes）；提供起终点时返回换乘方案（plan），
        含 data_source 字段标注数据来源
    """
    return _dp_get_transit_routes(city, origin, destination)


@mcp.tool(name="get_parking")
def get_parking(city: str) -> dict:
    """
    获取城市停车场

    参数：
        city (str): 城市名，如 北京 / 广州 / 上海

    返回值：
        dict: 停车场列表（items），含 data_source 字段标注数据来源
    """
    return _dp_get_parking(city)


@mcp.tool(name="get_poi")
def get_poi(city: str, poi_type: str) -> dict:
    """
    获取公共设施 POI

    参数：
        city (str): 城市名，如 北京 / 广州 / 上海
        poi_type (str): POI 类型，如 医院 / 图书馆 / 公园 / 政务大厅

    返回值：
        dict: POI 列表（items），含 data_source 字段标注数据来源
    """
    return _dp_get_poi(city, poi_type)


if __name__ == '__main__':
    # 注意：stdio 传输下 stdout 是 MCP 协议通道，启动日志必须写 stderr，否则污染协议流
    print(f"启动交通 MCP 服务: TrafficMCP（端口 {SERVER_PORT}，stdio 传输）", file=sys.stderr)
    # FastMCP 4.x 推荐 stdio 传输（供 MCP Client / 上层编排层连接）
    mcp.run(transport="stdio")
