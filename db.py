# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 数据库连接与通用 DAO 封装
基于 pymysql，提供连接获取 / 上下文管理器 / 通用增删改查
"""
import pymysql
from pymysql.cursors import DictCursor

from city_service_assistant.config import config
from city_service_assistant.create_logger import logger


def get_connection():
    """获取 MySQL 连接（DictCursor，utf8mb4）"""
    return pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


class Database:
    """数据库操作封装：execute / fetch / insert / update / delete"""

    def __init__(self, conn=None):
        self.conn = conn if conn is not None else get_connection()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        try:
            if self.conn and not self.conn._closed:
                self.conn.close()
        except Exception as e:  # noqa: BLE001
            logger.warning("关闭连接异常: %s", e)

    def execute(self, sql, params=None):
        """执行写操作，返回影响行数，自动提交"""
        try:
            with self.conn.cursor() as cur:
                rows = cur.execute(sql, params or ())
            self.conn.commit()
            return rows
        except Exception:
            self.conn.rollback()
            raise

    def query(self, sql, params=None, one=False):
        """查询，one=True 返回单行 dict，否则返回 list[dict]"""
        with self.conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone() if one else cur.fetchall()

    def insert(self, table, data: dict):
        keys = list(data.keys())
        cols = ", ".join(f"`{k}`" for k in keys)
        marks = ", ".join(["%s"] * len(keys))
        sql = f"INSERT INTO `{table}` ({cols}) VALUES ({marks})"
        return self.execute(sql, [data[k] for k in keys])

    def update(self, table, data: dict, where: str, params=None):
        sets = ", ".join(f"`{k}` = %s" for k in data)
        sql = f"UPDATE `{table}` SET {sets} WHERE {where}"
        return self.execute(sql, list(data.values()) + list(params or ()))

    def delete(self, table, where: str, params=None):
        sql = f"DELETE FROM `{table}` WHERE {where}"
        return self.execute(sql, params or ())


if __name__ == "__main__":
    with Database() as db:
        try:
            rows = db.query("SELECT 1 AS ok")
            logger.info("数据库连接正常: %s", rows)
        except Exception as e:
            logger.error("数据库连接失败: %s", e)
