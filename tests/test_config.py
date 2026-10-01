# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 配置模块单元测试

覆盖 config.py 的：
1. INTENT_AGENT_MAP 意图 → 子代理映射（气象/交通/生活政务三类）
2. A2A / MCP / API 服务端口配置
3. INDEPENDENT_INTENTS 独立意图集合
"""
from city_service_assistant.config import config


# ==================== 意图映射 ====================

def test_intent_map_weather_env():
    """气象环境类意图全部映射到 WeatherEnvAssistant"""
    for intent in ["weather", "air_quality", "weather_alert"]:
        assert config.INTENT_AGENT_MAP[intent] == "WeatherEnvAssistant"


def test_intent_map_traffic():
    """交通出行类意图全部映射到 TrafficAssistant"""
    for intent in ["traffic_status", "transit", "geocode", "parking"]:
        assert config.INTENT_AGENT_MAP[intent] == "TrafficAssistant"


def test_intent_map_life():
    """生活政务类意图全部映射到 LifeServiceAssistant（与 a2a_server/life_server.py 对齐）"""
    for intent in ["poi", "service_guide", "complaint"]:
        assert config.INTENT_AGENT_MAP[intent] == "LifeServiceAssistant"


def test_intent_map_all_agents_exist():
    """映射值集合恰好为三个子代理名"""
    assert set(config.INTENT_AGENT_MAP.values()) == {
        "WeatherEnvAssistant", "TrafficAssistant", "LifeServiceAssistant",
    }


# ==================== 端口配置 ====================

def test_a2a_ports():
    """三个 A2A 子代理端口：weather 5005 / traffic 5006 / life 5007"""
    assert config.A2A_WEATHER_PORT == 5005
    assert config.A2A_TRAFFIC_PORT == 5006
    assert config.A2A_LIFE_PORT == 5007
    # 三个端口必须互不相同，避免端口冲突
    assert len({config.A2A_WEATHER_PORT, config.A2A_TRAFFIC_PORT, config.A2A_LIFE_PORT}) == 3


def test_mcp_ports():
    """三个 MCP 工具服务端口：weather 8002 / traffic 8001 / life 8003"""
    assert config.MCP_WEATHER_PORT == 8002
    assert config.MCP_TRAFFIC_PORT == 8001
    assert config.MCP_LIFE_PORT == 8003


def test_api_server_port():
    """总代理 API 服务端口默认 8080"""
    assert config.API_SERVER_PORT == 8080


def test_ports_are_positive_ints():
    """所有服务端口均为正整数"""
    ports = [
        config.API_SERVER_PORT, config.MCP_WEATHER_PORT, config.MCP_TRAFFIC_PORT,
        config.MCP_LIFE_PORT, config.A2A_WEATHER_PORT, config.A2A_TRAFFIC_PORT,
        config.A2A_LIFE_PORT,
    ]
    for p in ports:
        assert isinstance(p, int) and p > 0


# ==================== 独立意图 ====================

def test_independent_intents_weather():
    """气象类意图均为独立意图（无需复杂规划）"""
    for intent in ["weather", "air_quality", "weather_alert"]:
        assert intent in config.INDEPENDENT_INTENTS


def test_independent_intents_traffic():
    """交通类意图均为独立意图"""
    for intent in ["traffic_status", "transit", "geocode", "parking"]:
        assert intent in config.INDEPENDENT_INTENTS


def test_complaint_not_independent():
    """投诉建议（complaint）属于需走规划流程的意图，不应在独立意图集合中"""
    assert "complaint" not in config.INDEPENDENT_INTENTS
