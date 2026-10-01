# -*- coding: utf-8 -*-
"""
需求：初始化政务办事指南 RAG 系统
思路：
1. 从 MySQL csp_db.service_guides 表读取全部办事指南
2. 使用 Qwen text-embedding-v3 API 将每条指南的 text 字段生成 1024 维向量
3. 在本地 Milvus 中创建 Collection（service_guides）并插入数据
4. 支持后续通过语义搜索匹配用户意图的办事指南
"""

import json
import os
import sys
import time
import requests
import pymysql
from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType, utility, MilvusException

# 将项目根目录加入 Python 路径，以便导入配置
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# ==================== Qwen Embedding API ====================
# 使用 DashScope 的 text-embedding-v3 模型生成向量
# 返回 1024 维向量
from city_service_assistant.config import Config

conf = Config()
DASHSCOPE_API_KEY = conf.DASHSCOPE_API_KEY  # 从项目配置获取 API Key
EMBEDDING_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"


def get_embedding(text: str, max_retries: int = 3, retry_delay: float = 1.0) -> list:
    """
    调用 Qwen Embedding API 生成文本向量

    参数：
        text (str): 需要生成向量的文本
        max_retries (int): 最大重试次数，默认 3 次
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
            response = requests.post(EMBEDDING_URL, headers=headers, json=payload, timeout=30)

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


# ==================== MySQL 数据读取 ====================
def load_guides_from_mysql() -> list:
    """
    从 MySQL csp_db.service_guides 表读取全部办事指南

    返回值：
        list: 办事指南记录列表，每条为 dict，含
              id / item_name / category / department / material_list / process / text
    """
    import pymysql.cursors

    connection = pymysql.connect(
        host=conf.MYSQL_HOST,
        port=conf.MYSQL_PORT,
        user=conf.MYSQL_USER,
        password=conf.MYSQL_PASSWORD,
        database=conf.MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT id, item_name, category, department, material_list, process, text "
                "FROM service_guides"
            )
            guides = cur.fetchall()
        return guides
    finally:
        connection.close()


# ==================== Milvus 初始化 ====================
MILVUS_HOST = conf.MILVUS_HOST
MILVUS_PORT = conf.MILVUS_PORT
COLLECTION_NAME = "service_guides"
DIMENSION = 1024  # text-embedding-v3 输出维度


def create_guide_collection():
    """
    在 Milvus 中创建政务办事指南 Collection

    字段设计（对齐 MySQL service_guides 表）：
    - id: 主键（取自 MySQL 表的 id）
    - item_name: 办事事项名
    - category: 分类（户籍/社保/医保等）
    - department: 办理部门
    - material_list: 所需材料清单
    - process: 办理流程
    - text: 事项全文（用于生成向量）
    - embedding: 向量（1024 维）
    """
    # 连接 Milvus（带重试）
    max_retries = 3
    for attempt in range(max_retries):
        try:
            connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
            print(f"已连接 Milvus: {MILVUS_HOST}:{MILVUS_PORT}")
            break
        except MilvusException as e:
            if attempt < max_retries - 1:
                print(f"  [警告] 连接 Milvus 失败 (第 {attempt + 1} 次): {e}")
                print(f"  2 秒后重试...")
                time.sleep(2)
            else:
                raise RuntimeError(f"无法连接 Milvus ({MILVUS_HOST}:{MILVUS_PORT})，已重试 {max_retries} 次: {e}")

    # 如果已存在则删除（带重试）
    for attempt in range(max_retries):
        try:
            if utility.has_collection(COLLECTION_NAME):
                print(f"集合 {COLLECTION_NAME} 已存在，删除重建")
                try:
                    # 先尝试释放集合，避免缓存问题
                    col = Collection(COLLECTION_NAME)
                    col.release()
                    time.sleep(0.5)
                except MilvusException:
                    pass  # 释放失败不影响后续删除
                utility.drop_collection(COLLECTION_NAME)
                print(f"集合 {COLLECTION_NAME} 删除成功")
                time.sleep(1)  # 等待 Milvus 清理完成
            break
        except MilvusException as e:
            if attempt < max_retries - 1:
                print(f"  [警告] 删除集合失败 (第 {attempt + 1} 次): {e}")
                print(f"  2 秒后重试...")
                time.sleep(2)
                # 重连 Milvus，清理可能的异常连接状态
                try:
                    connections.disconnect("default")
                    time.sleep(0.5)
                    connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
                    print(f"  已重新连接 Milvus")
                except MilvusException:
                    pass
            else:
                raise RuntimeError(f"无法删除集合 {COLLECTION_NAME}，已重试 {max_retries} 次: {e}")

    # 定义字段
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=False),
        FieldSchema(name="item_name", dtype=DataType.VARCHAR, max_length=100),
        FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=50),
        FieldSchema(name="department", dtype=DataType.VARCHAR, max_length=100),
        FieldSchema(name="material_list", dtype=DataType.VARCHAR, max_length=4000),
        FieldSchema(name="process", dtype=DataType.VARCHAR, max_length=4000),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8000),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=DIMENSION),
    ]

    schema = CollectionSchema(fields, description="政务办事指南表（RAG 向量检索）")
    collection = Collection(COLLECTION_NAME, schema)
    print(f"集合 {COLLECTION_NAME} 创建成功")

    # 创建向量索引
    index_params = {
        "index_type": "IVF_FLAT",
        "metric_type": "COSINE",
        "params": {"nlist": 64}
    }
    collection.create_index(field_name="embedding", index_params=index_params)
    print("向量索引创建成功 (IVF_FLAT, COSINE)")

    return collection


def insert_guides(collection, guides: list):
    """
    将办事指南生成向量后插入 Milvus
    """
    print(f"\n开始为 {len(guides)} 条办事指南生成向量...")
    rows = []
    failed_guides = []  # 记录失败的指南

    for i, guide in enumerate(guides):
        # 使用事项全文 text 作为 embedding 输入文本
        embedding_text = guide["text"] or ""

        if (i + 1) % 5 == 0:
            print(f"  已处理 {i + 1}/{len(guides)} 条...")

        try:
            embedding = get_embedding(embedding_text)
        except (RuntimeError, ValueError) as e:
            print(f"  [错误] 指南 {guide['id']} ({guide['item_name']}) 向量生成失败: {e}")
            failed_guides.append(guide["id"])
            continue  # 跳过失败的指南，继续处理其他指南

        rows.append({
            "id": guide["id"],
            "item_name": guide["item_name"],
            "category": guide["category"] or "",
            "department": guide["department"] or "",
            "material_list": guide["material_list"] or "",
            "process": guide["process"] or "",
            "text": embedding_text,
            "embedding": embedding,
        })

    if not rows:
        raise RuntimeError("所有办事指南向量生成均失败，无法插入数据")

    # 批量插入（带重试）
    for attempt in range(3):
        try:
            collection.insert(rows)
            collection.flush()  # 刷盘
            print(f"成功插入 {len(rows)} 条办事指南数据")
            break
        except MilvusException as e:
            if attempt < 2:
                print(f"  [警告] 插入失败 (第 {attempt + 1} 次): {e}")
                time.sleep(2)
            else:
                raise RuntimeError(f"数据插入 Milvus 失败，已重试 3 次: {e}")

    # 报告失败的指南
    if failed_guides:
        print(f"\n[注意] 以下 {len(failed_guides)} 条指南因向量生成失败未插入: {', '.join(map(str, failed_guides))}")


def test_search(collection):
    """
    测试语义搜索：用自然语言查询政务办事指南
    """
    # 测试查询
    test_queries = [
        "我想办理户口迁移，需要准备什么材料",
        "如何申请城乡居民医保报销",
        "身份证丢失了怎么补办",
        "办理护照需要哪些材料",
        "新生儿出生医学证明怎么办理",
    ]

    print("\n=== 语义搜索测试 ===")
    for query in test_queries:
        print(f"\n查询: {query}")
        try:
            query_embedding = get_embedding(query)
        except (RuntimeError, ValueError) as e:
            print(f"  [错误] 查询向量生成失败: {e}")
            continue

        try:
            collection.load()
            results = collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {"nprobe": 10}},
                limit=2,
                output_fields=["id", "item_name", "category", "department", "text"]
            )

            for hits in results:
                if not hits:
                    print("  未找到匹配结果")
                for hit in hits:
                    print(f"  [{hit.entity.get('id')}] {hit.entity.get('item_name')} "
                          f"- {hit.entity.get('category')} "
                          f"距离: {hit.distance:.4f}")
        except MilvusException as e:
            print(f"  [错误] Milvus 搜索失败: {e}")


if __name__ == '__main__':
    try:
        guides = load_guides_from_mysql()
        print(f"从 MySQL 读取到 {len(guides)} 条办事指南")
        if not guides:
            print("service_guides 表无数据，请先执行 init_db.py / seed 脚本初始化数据")
            sys.exit(0)
        collection = create_guide_collection()
        insert_guides(collection, guides)
        test_search(collection)
    except Exception as e:
        print(f"\n[致命错误] 程序执行失败: {e}")
        sys.exit(1)
