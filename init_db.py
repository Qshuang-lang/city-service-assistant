# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 数据层初始化脚本
用法（在 D:\\car 目录下）：
    python -m city_service_assistant.init_db            # 建库建表 + 导入种子
    python -m city_service_assistant.init_db --fetch    # 建库后额外拉取真实 API 数据
    python -m city_service_assistant.init_db --force    # 清空重建
"""
import argparse
import os

import pymysql

from city_service_assistant.config import config
from city_service_assistant.create_logger import logger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQL_DIR = os.path.join(BASE_DIR, "sql")
CREATE_SQL = os.path.join(SQL_DIR, "create_all_tables.sql")
SEED_SQL = os.path.join(SQL_DIR, "insert_seed_data.sql")
# 种子数据增强补丁：更新过期天气、扩充空气质量/路况/地铁线路/政务指南（幂等，可重复执行）
SEED_ENHANCE_SQL = os.path.join(SQL_DIR, "seed_enhance.sql")


def _run_script(conn, sql_path: str, db_selected: bool = True):
    """执行一个 SQL 脚本文件。db_selected=False 时用于先建库（脚本自带 USE）。"""
    with open(sql_path, "r", encoding="utf-8") as f:
        script = f.read()
    # 按分号拆分语句（简单拆分，SQL 中不含存储过程）
    statements = [s.strip() for s in script.split(";") if s.strip()]
    cur = conn.cursor()
    for stmt in statements:
        if not stmt:
            continue
        cur.execute(stmt)
    conn.commit()
    cur.close()
    logger.info("已执行脚本: %s（%d 条语句）", sql_path, len(statements))


def init_database(force: bool = False):
    """建库建表 + 导入种子数据"""
    # 1. 连接 MySQL 服务（不选库）
    conn = pymysql.connect(
        host=config.MYSQL_HOST, port=config.MYSQL_PORT,
        user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
        charset="utf8mb4",
    )
    try:
        if force:
            logger.info("强制重建：删除数据库 %s", config.MYSQL_DATABASE)
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{config.MYSQL_DATABASE}`")
            conn.commit()

        # 2. 建库建表（脚本内含 CREATE DATABASE + USE，不选库执行）
        _run_script(conn, CREATE_SQL, db_selected=False)

        # 3. 导入种子数据（需已选中库，脚本内有 USE）
        _run_script(conn, SEED_SQL, db_selected=False)

        # 4. 应用种子数据增强补丁（替换过期日期、扩充数据量）
        if os.path.exists(SEED_ENHANCE_SQL):
            _run_script(conn, SEED_ENHANCE_SQL, db_selected=False)
        else:
            logger.info("未找到种子增强补丁 %s，跳过", SEED_ENHANCE_SQL)

        logger.info("数据层初始化完成：数据库 %s 已就绪", config.MYSQL_DATABASE)
    finally:
        conn.close()


def fetch_real_data(cities=None):
    """初始化后拉取真实 API 数据（可选步骤）"""
    from city_service_assistant.utils.spider_weather import update_weather
    from city_service_assistant.utils.spider_amap import update_amap
    update_weather(force_update=True, cities=cities)
    update_amap(force_update=True, cities=cities)


def main():
    parser = argparse.ArgumentParser(description="城市公共服务数据层初始化")
    parser.add_argument("--fetch", action="store_true", help="初始化后拉取真实 API 数据")
    parser.add_argument("--force", action="store_true", help="强制清空重建")
    parser.add_argument("--cities", nargs="*", default=None, help="指定城市（仅 --fetch 生效）")
    args = parser.parse_args()

    init_database(force=args.force)
    if args.fetch:
        fetch_real_data(cities=args.cities)


if __name__ == "__main__":
    main()
