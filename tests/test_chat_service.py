# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 主路由服务（chat_service）单元测试

覆盖 ChatService 纯逻辑方法（mock LLM 与数据库，不触发真实网络/模型调用）：
1. intent_agent —— 意图识别结果解析（mock 提示词链返回 JSON）
2. _should_skip_planning —— 启发式路由判定
3. get_agent_cards —— 子代理卡片信息
4. get_memory_state —— 记忆状态摘要
5. update_user_profile / clear_memory —— 画像更新与记忆清空

通过 object.__new__ 构造轻量实例 + FakeMemory 替换 memory，隔离 __init__ 的数据库副作用。
"""
from types import SimpleNamespace

import city_service_assistant.chat_service as cs


class FakeMemory:
    """模拟 memory.ConversationMemory，避免连接 MySQL"""

    def __init__(self):
        self.short_term_messages = [
            {"role": "user", "content": "北京今天天气怎么样", "timestamp": "2026-09-13 10:00:00"},
            {"role": "assistant", "content": "北京今天晴，气温 30℃", "timestamp": "2026-09-13 10:00:01"},
        ]
        self.user_profile = {"city": "北京", "commute": "地铁"}
        self.current_task = {}
        self.entity_history = [
            {"type": "weather", "query": "北京今天天气", "timestamp": "2026-09-13 10:00:00"},
        ]
        self.profile_updated = None
        self.clear_called = False

    def get_short_term_text(self):
        return "北京今天天气怎么样\n北京今天晴，气温 30℃"

    def get_profile_text(self):
        return "城市: 北京, 通勤: 地铁"

    def update_profile(self, profile):
        self.profile_updated = profile

    def clear(self):
        self.clear_called = True


def make_service():
    """构造轻量 ChatService 实例（绕过 __init__ 的 LLM/DB 初始化）"""
    svc = object.__new__(cs.ChatService)
    svc.memory = FakeMemory()
    svc.messages = []
    svc.conversation_history = ""
    svc.llm = None  # 仅作占位：FakePrompt.__or__ 忽略 llm
    svc.agent_urls = {
        "WeatherEnvAssistant": "http://localhost:5005",
        "TrafficAssistant": "http://localhost:5006",
        "LifeServiceAssistant": "http://localhost:5007",
    }
    return svc


# ==================== 启发式路由 ====================

def test_should_skip_planning_single_intent():
    """单意图直接执行，跳过规划"""
    svc = make_service()
    assert svc._should_skip_planning(["weather"]) is True


def test_should_skip_planning_multi_independent():
    """多意图但均为独立查询类意图，仍跳过规划"""
    svc = make_service()
    assert svc._should_skip_planning(["weather", "traffic_status"]) is True


def test_should_skip_planning_needs_plan():
    """含需分步处理意图（如 complaint）时进入规划"""
    svc = make_service()
    assert svc._should_skip_planning(["weather", "complaint"]) is False


def test_should_skip_planning_multi_with_unknown_needs_plan():
    """多意图中含未知意图时进入规划流程"""
    svc = make_service()
    assert svc._should_skip_planning(["weather", "unknown_intent"]) is False


# ==================== 子代理卡片 ====================

def test_get_agent_cards_three_agents():
    """get_agent_cards 返回 3 张子代理卡片，信息完整且状态在线"""
    svc = make_service()
    cards = svc.get_agent_cards()
    assert len(cards) == 3
    names = {c["name"] for c in cards}
    assert names == {"WeatherEnvAssistant", "TrafficAssistant", "LifeServiceAssistant"}
    for card in cards:
        assert card["status"] == "在线"
        assert card["description"]
        assert isinstance(card["skills"], list) and card["skills"]
        assert card["url"].startswith("http://localhost:")


# ==================== 记忆状态 ====================

def test_get_memory_state_structure():
    """get_memory_state 返回完整记忆结构，role 已中文化"""
    svc = make_service()
    state = svc.get_memory_state()
    assert "short_term_messages" in state
    assert "user_profile" in state
    assert "current_task" in state
    assert "entity_history" in state
    assert state["user_profile"]["city"] == "北京"
    assert state["short_term_messages"][0]["role"] == "用户"
    assert state["short_term_messages"][1]["role"] == "助手"


# ==================== 画像更新 / 记忆清空 ====================

def test_update_user_profile():
    """update_user_profile 透传画像到 memory"""
    svc = make_service()
    svc.update_user_profile({"city": "上海"})
    assert svc.memory.profile_updated == {"city": "上海"}


def test_clear_memory():
    """clear_memory 清空 memory、messages 与对话历史"""
    svc = make_service()
    svc.messages = [{"role": "user", "content": "x"}]
    svc.conversation_history = "User: x"
    svc.clear_memory()
    assert svc.memory.clear_called is True
    assert svc.messages == []
    assert svc.conversation_history == ""


# ==================== 意图识别（mock 提示词链） ====================

class FakeChain:
    """模拟 langchain Runnable，invoke 返回带 content 的假消息"""

    def __init__(self, text):
        self._text = text

    def invoke(self, *args, **kwargs):
        return SimpleNamespace(content=self._text)


class FakePrompt:
    """模拟 ChatPromptTemplate：| llm 组装为 FakeChain"""

    def __init__(self, text):
        self._text = text

    def __or__(self, other):
        return FakeChain(self._text)


def test_intent_agent_parses_json(monkeypatch):
    """intent_agent 正确剥离 ```json 围栏并解析意图输出"""
    canned = (
        '```json\n'
        '{"intents": ["weather"], "user_queries": {"weather": "北京今天天气"}, '
        '"follow_up_message": ""}\n'
        '```'
    )
    monkeypatch.setattr(cs.CityServicePrompts, "intent_prompt",
                        staticmethod(lambda: FakePrompt(canned)))

    svc = make_service()
    intents, user_queries, follow_up = svc.intent_agent("北京今天天气怎么样")

    assert intents == ["weather"]
    assert user_queries["weather"] == "北京今天天气"
    assert follow_up == ""


def test_intent_agent_out_of_scope(monkeypatch):
    """意图识别返回 out_of_scope 时正确解析"""
    canned = (
        '{"intents": ["out_of_scope"], "user_queries": {}, '
        '"follow_up_message": "该问题不在我的服务范围内，请咨询 12345。"}'
    )
    monkeypatch.setattr(cs.CityServicePrompts, "intent_prompt",
                        staticmethod(lambda: FakePrompt(canned)))

    svc = make_service()
    intents, _, follow_up = svc.intent_agent("今天股票涨了吗")

    assert intents == ["out_of_scope"]
    assert "12345" in follow_up
