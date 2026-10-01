# -*- coding: utf-8 -*-
"""
政务办事指南 RAG 语义检索包

模块说明：
- init_guide_rag.py   从 MySQL csp_db.service_guides 读取办事指南，
                      用 Qwen text-embedding-v3 向量化后写入 Milvus（初始化向量库）
- search_guide_rag.py 提供语义检索函数 search_guides()，输入自然语言查询，
                      从 Milvus 返回最匹配的办事指南详情

使用方式：
    初始化向量库（需先启动 MySQL 与 Milvus）：
        python -m city_service_assistant.rag.init_guide_rag

    语义检索：
        from city_service_assistant.rag.search_guide_rag import search_guides
        results = search_guides("我想办理户口迁移，需要准备什么材料")
"""
from .search_guide_rag import search_guides, get_collection

__all__ = ["search_guides", "get_collection"]
