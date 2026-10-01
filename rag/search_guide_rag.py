# -*- coding: utf-8 -*-
"""
需求：政务办事指南 RAG 语义检索模块
思路：
1. 输入自然语言查询，调用 Qwen Embedding API 生成查询向量
2. 在 Milvus 的 service_guides 集合中做向量相似度检索
3. 返回最匹配的办事指南详情（支持按分类过滤）

降级链路：Milvus 未启动 / 向量库未初始化 / Embedding API 不可用时，
search_guides_with_fallback 自动降级为 SQL 关键词检索（读 MySQL service_guides），
保证政务指南查询在基础设施缺失时仍可用（与 README 描述一致）。
"""

import os
import re
import sys
import time
import requests
from pymilvus import connections, Collection, utility, MilvusException

# 将项目根目录加入 Python 路径，以便导入配置
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# ==================== Qwen Embedding API ====================
# 使用 DashScope 的 text-embedding-v3 模型生成向量
# 返回 1024 维向量
from city_service_assistant.config import Config

conf = Config()
DASHSCOPE_API_KEY = conf.DASHSCOPE_API_KEY  # 从项目配置获取 API Key
EMBEDDING_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"

# ==================== Milvus 配置 ====================
MILVUS_HOST = conf.MILVUS_HOST
MILVUS_PORT = conf.MILVUS_PORT
COLLECTION_NAME = "service_guides"
DIMENSION = 1024  # text-embedding-v3 输出维度

# 语义检索返回字段（对齐 service_guides 表）
OUTPUT_FIELDS = ["id", "item_name", "category", "department", "material_list", "process", "text"]


def get_embedding(text: str, max_retries: int = 2, retry_delay: float = 1.0) -> list:
    """
    调用 Qwen Embedding API 生成文本向量

    参数：
        text (str): 需要生成向量的文本
        max_retries (int): 最大重试次数，默认 2 次
        retry_delay (float): 重试间隔（秒），默认 1 秒

    返回值：
        list: 1024 维向量

    异常：
        ValueError: 当输入文本为空或 API 返回格式异常时抛出
        RuntimeError: 当 API 调用失败且重试耗尽时抛出
    """
    # 输入验证
    if not text or not isinstance(text, str):
        raise ValueError("输入文本不能为空且必须是字符串类型")

    text = text.strip()
    if not text:
        raise ValueError("输入文本不能为空或只包含空白字符")

    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "text-embedding-v3",
        "input": [text],
        "dimensions": 1024
    }

    last_exception = None
    for attempt in range(max_retries):
        try:
            response = requests.post(EMBEDDING_URL, headers=headers, json=payload, timeout=15)

            # 检查 HTTP 状态码
            if response.status_code != 200:
                error_msg = f"API 请求失败，状态码: {response.status_code}"
                try:
                    error_detail = response.json()
                    if "error" in error_detail:
                        error_msg += f", 错误信息: {error_detail['error'].get('message', '未知错误')}"
                except Exception:
                    error_msg += f", 响应内容: {response.text[:200]}"

                # 4xx 客户端错误不重试（如认证失败、参数错误）
                if 400 <= response.status_code < 500:
                    raise ValueError(error_msg)

                # 5xx 服务端错误可以重试
                raise RuntimeError(error_msg)

            # 解析 JSON 响应
            try:
                result = response.json()
            except requests.exceptions.JSONDecodeError as e:
                raise RuntimeError(f"API 返回的不是有效的 JSON: {e}")

            # 验证响应格式
            if "data" not in result or not isinstance(result["data"], list) or len(result["data"]) == 0:
                raise ValueError(f"API 返回格式异常，缺少 data 字段: {result}")

            if "embedding" not in result["data"][0]:
                raise ValueError(f"API 返回格式异常，缺少 embedding 字段: {result['data'][0]}")

            embedding = result["data"][0]["embedding"]

            # 验证向量维度
            if not isinstance(embedding, list) or len(embedding) != 1024:
                raise ValueError(f"向量维度异常，期望 1024 维，实际: {len(embedding) if isinstance(embedding, list) else '非列表类型'}")

            return embedding

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.RequestException) as e:
            last_exception = e
            if attempt < max_retries - 1:
                print(f"  [警告] 网络请求失败 (第 {attempt + 1} 次尝试): {e}")
                print(f"  {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
                # 指数退避
                retry_delay *= 2
            else:
                break

        except (ValueError, RuntimeError) as e:
            # 对于客户端错误（ValueError），不重试直接抛出
            if isinstance(e, ValueError) and "API 请求失败，状态码: 4" in str(e):
                raise
            last_exception = e
            if attempt < max_retries - 1:
                print(f"  [警告] 请求失败 (第 {attempt + 1} 次尝试): {e}")
                print(f"  {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                break

    # 所有重试都失败
    raise RuntimeError(f"API 调用失败，已重试 {max_retries} 次: {last_exception}")


def get_collection() -> Collection:
    """
    连接 Milvus 并获取 service_guides 集合

    返回值：
        Collection: 已连接的 Milvus 集合对象

    异常：
        RuntimeError: 当连接 Milvus 失败或集合不存在时抛出
    """
    # 连接 Milvus（带重试；Milvus 不可达时快速失败，由上层降级为 SQL 检索）
    max_retries = 2
    for attempt in range(max_retries):
        try:
            connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT,
                                timeout=5000)  # 5s 超时，避免基础设施缺失时长时间挂起
            break
        except MilvusException as e:
            if attempt < max_retries - 1:
                print(f"  [警告] 连接 Milvus 失败 (第 {attempt + 1} 次): {e}")
                time.sleep(1)
            else:
                raise RuntimeError(f"无法连接 Milvus ({MILVUS_HOST}:{MILVUS_PORT})，已重试 {max_retries} 次: {e}")

    # 校验集合是否存在
    if not utility.has_collection(COLLECTION_NAME):
        raise RuntimeError(f"集合 {COLLECTION_NAME} 不存在，请先运行 init_guide_rag.py 初始化向量库")

    return Collection(COLLECTION_NAME)


def search_guides(query: str, top_k: int = 3, category: str = None,
                  collection: Collection = None) -> list:
    """
    语义检索政务办事指南

    参数：
        query (str): 自然语言查询，如 "我想办理户口迁移，需要准备什么材料"
        top_k (int): 返回最相似的条数，默认 3
        category (str, optional): 按分类过滤，如 户籍/社保/医保，默认不过滤
        collection (Collection, optional): 已连接的 Milvus 集合；不传则自动连接

    返回值：
        list: 检索结果列表，每项为 dict，含
              id / item_name / category / department / material_list / process / text / distance
    """
    if not query or not isinstance(query, str):
        raise ValueError("查询内容不能为空且必须是字符串类型")

    query = query.strip()
    if not query:
        raise ValueError("查询内容不能为空或只包含空白字符")

    # 生成查询向量
    query_embedding = get_embedding(query)

    # 获取集合
    col = collection if collection is not None else get_collection()
    col.load()

    # 构造分类过滤表达式（可选）
    expr = None
    if category:
        category = category.strip()
        if category:
            expr = f'category == "{category}"'

    # 执行向量检索
    results = col.search(
        data=[query_embedding],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"nprobe": 10}},
        limit=top_k,
        expr=expr,
        output_fields=OUTPUT_FIELDS,
    )

    # 组装返回结果
    guides = []
    for hits in results:
        for hit in hits:
            entity = hit.entity
            guide = {
                "id": entity.get("id"),
                "item_name": entity.get("item_name"),
                "category": entity.get("category"),
                "department": entity.get("department"),
                "material_list": entity.get("material_list"),
                "process": entity.get("process"),
                "text": entity.get("text"),
                "distance": round(float(hit.distance), 4),
            }
            guides.append(guide)

    return guides


def search_guides_sql(query: str, top_k: int = 3, category: str = None) -> list:
    """SQL 关键词降级检索：读 MySQL service_guides，按关键词匹配打分返回 TopK。

    不依赖 Milvus / Embedding API，Milvus 不可用时保证政务指南查询可用。
    返回结果结构与 search_guides 一致（含 distance 字段，数值为匹配得分）。
    """
    from city_service_assistant.utils.data_provider import get_service_guide

    query = (query or "").strip()
    if not query:
        raise ValueError("查询内容不能为空或只包含空白字符")

    # 中文分词：按 2-gram + 常用分隔符切词，避免逐字匹配噪音
    def tokenize(text: str) -> set:
        text = re.sub(r"[\s，。、；：！？,.!?/\\|（）()\[\]【】\"'“”‘’《》<>]+", "", text)
        tokens = set()
        if len(text) == 1:
            tokens.add(text)
            return tokens
        for i in range(len(text) - 1):
            tokens.add(text[i:i + 2])
        return tokens

    q_tokens = tokenize(query)

    guides = get_service_guide(category)
    items = list(guides.get("items", []))

    scored = []
    for item in items:
        haystack = " ".join([
            str(item.get("item_name", "")),
            str(item.get("category", "")),
            str(item.get("department", "")),
            str(item.get("material_list", "")),
            str(item.get("process", "")),
            str(item.get("text", "")),
        ])
        h_tokens = tokenize(haystack)
        hits = len(q_tokens & h_tokens)
        if hits > 0:
            # 完整子串命中加权，得分 = 命中数 + 子串加权（0~1）
            bonus = 1.0 if query in haystack else 0.0
            scored.append({
                "id": item.get("id"),
                "item_name": item.get("item_name"),
                "category": item.get("category"),
                "department": item.get("department"),
                "material_list": item.get("material_list"),
                "process": item.get("process"),
                "text": item.get("text"),
                "distance": round(-(hits + bonus), 4),  # 负数越小越相似，与向量距离语义一致
            })

    scored.sort(key=lambda x: x["distance"])
    return scored[:top_k]


def search_guides_with_fallback(query: str, top_k: int = 3, category: str = None) -> dict:
    """带降级的语义检索入口：优先 Milvus RAG，失败自动降级 SQL 关键词。

    返回 dict：{"query", "items", "data_source", "engine"}；
    engine 取值 milvus_rag / sql_fallback。
    """
    try:
        results = search_guides(query, top_k=top_k, category=category)
        return {
            "query": query,
            "items": results,
            "data_source": "milvus_rag",
            "engine": "milvus_rag",
        }
    except Exception as e:  # noqa: BLE001 —— Milvus/Embedding 不可用时降级
        results = search_guides_sql(query, top_k=top_k, category=category)
        return {
            "query": query,
            "items": results,
            "data_source": "sql_fallback",
            "engine": "sql_fallback",
            "fallback_reason": str(e),
        }


if __name__ == '__main__':
    try:
        test_query = "我想办理户口迁移，需要准备什么材料"
        print(f"查询: {test_query}")
        results = search_guides(test_query, top_k=3)
        if not results:
            print("未找到匹配结果")
        for r in results:
            print(f"  [{r['id']}] {r['item_name']} ({r['category']}) "
                  f"距离: {r['distance']}")
            print(f"      办理部门: {r['department']}")
            print(f"      材料清单: {r['material_list']}")
    except Exception as e:
        print(f"\n[致命错误] 程序执行失败: {e}")
        sys.exit(1)
