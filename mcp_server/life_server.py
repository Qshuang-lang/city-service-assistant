# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 生活政务 MCP 服务（FastMCP 协议）

功能：
- get_service_guide(category)  按分类查询政务办事指南（读 MySQL service_guides）
- search_guides(query, top_k, category)  政务办事指南大模型语义检索（RAG，Milvus 向量库）

数据链路：
- get_service_guide 走 data_provider（读种子表，data_source=simulated）
- search_guides 走 rag.search_guide_rag（Qwen text-embedding-v3 + Milvus 语义检索）；
  当 Milvus 未启动 / 未初始化向量库 / 未配置 DASHSCOPE_API_KEY 时，返回友好错误提示而非抛出异常。

端口：8003（复用 config.MCP_LIFE_PORT）
启动：python -m city_service_assistant.mcp_server.life_server（stdio 传输）
"""

import os
import sys

# 将项目根目录加入 Python 路径，以便导入配置、数据访问层与 RAG 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from fastmcp import FastMCP

from city_service_assistant.config import config
from city_service_assistant.utils.data_provider import get_service_guide as _dp_get_service_guide
from city_service_assistant.rag.search_guide_rag import search_guides_with_fallback as _rag_search_guides

# 服务端口：8003（生活政务）
SERVER_PORT = config.MCP_LIFE_PORT

# 创建 FastMCP 服务（stdin/stdout 走 stdio 协议）
mcp = FastMCP(
    "LifeMCP",
    instructions="生活政务服务信息：按分类查询办事指南、基于大模型语义检索办事指南（RAG），返回结果含 data_source 数据来源标注。",
)


@mcp.tool(name="get_service_guide")
def get_service_guide(category: str = None) -> dict:
    """
    按分类查询政务办事指南

    参数：
        category (str, optional): 分类，如 户籍 / 社保 / 医保；不传则返回全部

    返回值：
        dict: 指南列表（items），含 data_source 字段标注数据来源
    """
    return _dp_get_service_guide(category)


@mcp.tool(name="search_guides")
def search_guides(query: str, top_k: int = 3, category: str = None) -> dict:
    """
    大模型语义检索政务办事指南（RAG，Milvus 不可用时自动降级为 SQL 关键词检索）

    参数：
        query (str): 自然语言查询，如 "我想办理户口迁移，需要准备什么材料"
        top_k (int): 返回最相似的条数，默认 3
        category (str, optional): 按分类过滤，如 户籍 / 社保 / 医保，默认不过滤

    返回值：
        dict: 检索结果（items，含相似度 distance），data_source=engine 实际来源
              （milvus_rag / sql_fallback）
    """
    try:
        return _rag_search_guides(query, top_k=top_k, category=category)
    except Exception as e:  # noqa: BLE001 —— 兜底保护：连 SQL 降级都失败时给出友好提示
        return {
            "error": f"政务指南检索暂不可用: {e}",
            "hint": "请确认 MySQL 服务已启动（service_guides 表存在且已填充种子数据）。",
            "data_source": "error",
        }


if __name__ == '__main__':
    # 注意：stdio 传输下 stdout 是 MCP 协议通道，启动日志必须写 stderr，否则污染协议流
    print(f"启动生活政务 MCP 服务: LifeMCP（端口 {SERVER_PORT}，stdio 传输）", file=sys.stderr)
    # FastMCP 4.x 推荐 stdio 传输（供 MCP Client / 上层编排层连接）
    mcp.run(transport="stdio")
