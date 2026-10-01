# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 记忆模块（ConversationMemory）

同构复刻 SmartVoyage 参考项目 memory.py，适配 D:\\car 现有数据层：
- 内存层：短期对话（short_term_messages）、用户画像（user_profile）、
  当前任务（current_task）、实体历史（entity_history）
- 持久层：基于现有 db.py（pymysql 封装）与 sql/create_all_tables.sql 三张记忆表
    * user_profiles      (user_id, pref_key, pref_value) —— UPSERT
    * short_term_messages(role, content, message_time, message_order) —— DELETE + INSERT
    * query_history      (user_id, intent_type, query_content, response, query_time) —— INSERT
- 连接策略：每次持久化操作通过 db.Database() 获取独立连接（自动关闭），
  避免长驻连接失效；连接失败仅告警，不阻断主流程。

方法接口与参考项目保持一致，供 chat_service / api_server 直接复用：
    add_message / update_profile / update_task_context / extract_entities / clear
    get_short_term_text / get_profile_text / to_dict / from_dict
    save_messages_to_db / load_messages_from_db / save_profile_to_db / load_profile_from_db
    save_entity_to_db / load_entities_from_db / clear_all_from_db
"""
import json
from datetime import datetime

import pytz

from city_service_assistant.create_logger import logger

# Asia/Shanghai 时区，保证记忆时间戳与本地一致
_TZ = pytz.timezone("Asia/Shanghai")


def _now_hm() -> str:
    """当前时间 HH:MM:SS"""
    return datetime.now(_TZ).strftime("%H:%M:%S")


def _now_dt() -> str:
    """当前时间 %Y-%m-%d %H:%M:%S"""
    return datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")


class ConversationMemory:
    """对话记忆管理：短期对话 / 用户画像 / 当前任务 / 实体历史，MySQL 持久化"""

    def __init__(self, short_term_limit: int = 10, user_id: str = "default"):
        # 内存层
        self.short_term_messages = []   # 短期对话，最多 short_term_limit 条
        self.user_profile = {}          # 用户画像，如 {"home_city": "北京"}
        self.current_task = {}          # 当前任务上下文，如 {"type": "traffic_status", "query": "..."}
        self.short_term_limit = short_term_limit
        self.entity_history = []        # 历史提取的实体记录
        # 持久层参数
        self.user_id = user_id          # 用户标识（对应三张记忆表的 user_id 字段）

    # ==================== 写操作（内存 + 持久化） ====================

    def add_message(self, role: str, content: str):
        """添加一条对话消息到短期记忆并持久化"""
        self.short_term_messages.append({
            "role": role,
            "content": content,
            "timestamp": _now_hm(),
        })
        if len(self.short_term_messages) > self.short_term_limit:
            self.short_term_messages = self.short_term_messages[-self.short_term_limit:]
        self.save_messages_to_db()

    def update_profile(self, profile_update: dict):
        """更新用户画像并持久化"""
        self.user_profile.update(profile_update)
        self.save_profile_to_db()

    def update_task_context(self, task_update: dict):
        """更新当前任务上下文（仅内存，不落库）"""
        self.current_task.update(task_update)

    def extract_entities(self, intent_type: str, query: str, response: str = ""):
        """提取关键实体到历史并持久化（query_history 表）"""
        self.entity_history.append({
            "type": intent_type,
            "query": query,
            "timestamp": _now_dt(),
        })
        if len(self.entity_history) > 20:
            self.entity_history = self.entity_history[-20:]
        self.save_entity_to_db(intent_type, query, response)

    def clear(self):
        """清空内存 + 数据库中的全部记忆"""
        self.short_term_messages = []
        self.user_profile = {}
        self.current_task = {}
        self.entity_history = []
        self.clear_all_from_db()

    # ==================== 读操作 ====================

    def get_short_term_text(self) -> str:
        """短期对话的文本格式，供意图识别 / 子代理调用注入"""
        lines = []
        for msg in self.short_term_messages:
            role_label = "User" if msg["role"] == "user" else "Assistant"
            lines.append(f"{role_label}: {msg['content']}")
        return "\n".join(lines)

    def get_profile_text(self) -> str:
        """用户画像的文本描述，注入 prompt"""
        if not self.user_profile:
            return "无已知的用户画像"
        return "，".join(f"{k}: {v}" for k, v in self.user_profile.items())

    # ==================== 序列化 ====================

    def to_dict(self) -> dict:
        return {
            "short_term_messages": self.short_term_messages,
            "user_profile": self.user_profile,
            "current_task": self.current_task,
            "entity_history": self.entity_history[-5:],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationMemory":
        memory = cls()
        memory.short_term_messages = data.get("short_term_messages", [])
        memory.user_profile = data.get("user_profile", {})
        memory.current_task = data.get("current_task", {})
        memory.entity_history = data.get("entity_history", [])
        return memory

    # ==================== 数据库持久化（基于 db.py Database） ====================

    def save_messages_to_db(self):
        """短期对话覆盖写入：DELETE 全部 + 批量 INSERT"""
        try:
            from city_service_assistant.db import Database
            with Database() as db:
                db.execute("DELETE FROM short_term_messages")
                for i, msg in enumerate(self.short_term_messages):
                    db.execute(
                        "INSERT INTO short_term_messages (role, content, message_time, message_order) "
                        "VALUES (%s, %s, %s, %s)",
                        (msg["role"], msg["content"], msg["timestamp"], i),
                    )
        except Exception as e:  # noqa: BLE001 —— 记忆写入失败不阻断主流程
            logger.warning("保存短期对话到数据库失败: %s", e)

    def load_messages_from_db(self):
        """从数据库加载短期对话"""
        try:
            from city_service_assistant.db import Database
            with Database() as db:
                rows = db.query(
                    "SELECT role, content, message_time FROM short_term_messages "
                    "ORDER BY message_order ASC",
                )
            self.short_term_messages = [
                {"role": r["role"], "content": r["content"], "timestamp": r["message_time"]}
                for r in rows
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("从数据库加载短期对话失败: %s", e)

    def save_profile_to_db(self):
        """用户画像 UPSERT（user_id + pref_key 唯一键）"""
        try:
            from city_service_assistant.db import Database
            with Database() as db:
                for key, value in self.user_profile.items():
                    db.execute(
                        "INSERT INTO user_profiles (user_id, pref_key, pref_value) "
                        "VALUES (%s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE pref_value = VALUES(pref_value), "
                        "updated_at = CURRENT_TIMESTAMP",
                        (self.user_id, key, str(value)),
                    )
        except Exception as e:  # noqa: BLE001
            logger.warning("保存用户画像到数据库失败: %s", e)

    def load_profile_from_db(self):
        """从数据库加载用户画像"""
        try:
            from city_service_assistant.db import Database
            with Database() as db:
                rows = db.query(
                    "SELECT pref_key, pref_value FROM user_profiles WHERE user_id=%s",
                    (self.user_id,),
                )
            self.user_profile = {r["pref_key"]: r["pref_value"] for r in rows}
        except Exception as e:  # noqa: BLE001
            logger.warning("从数据库加载用户画像失败: %s", e)

    def save_entity_to_db(self, intent_type: str, query: str, response: str = ""):
        """插入一条查询历史到 query_history"""
        try:
            from city_service_assistant.db import Database
            with Database() as db:
                db.execute(
                    "INSERT INTO query_history (user_id, intent_type, query_content, response, query_time) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (self.user_id, intent_type,
                     json.dumps({"query": query}, ensure_ascii=False), response, _now_dt()),
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("保存查询历史到数据库失败: %s", e)

    def load_entities_from_db(self, limit: int = 20):
        """从数据库加载查询历史，按时间倒序取最近 N 条，再翻转成正序"""
        try:
            from city_service_assistant.db import Database
            with Database() as db:
                rows = db.query(
                    "SELECT intent_type, query_content, query_time FROM query_history "
                    "WHERE user_id=%s ORDER BY query_time DESC LIMIT %s",
                    (self.user_id, limit),
                )
            rows = rows[::-1]  # 倒序取回后翻转为正序（fetchall 返回 tuple，不能用 .reverse()）
            self.entity_history = []
            for row in rows:
                try:
                    query_text = json.loads(row["query_content"]).get("query", "")
                except Exception:  # noqa: BLE001
                    query_text = ""
                self.entity_history.append({
                    "type": row["intent_type"],
                    "query": query_text,
                    "timestamp": row["query_time"].strftime("%Y-%m-%d %H:%M:%S") if row["query_time"] else "",
                })
        except Exception as e:  # noqa: BLE001
            logger.warning("从数据库加载查询历史失败: %s", e)

    def clear_all_from_db(self):
        """清空数据库中的全部记忆数据"""
        try:
            from city_service_assistant.db import Database
            with Database() as db:
                db.execute("DELETE FROM short_term_messages")
                db.execute("DELETE FROM query_history")
                db.execute("DELETE FROM user_profiles")
        except Exception as e:  # noqa: BLE001
            logger.warning("清空数据库记忆失败: %s", e)
