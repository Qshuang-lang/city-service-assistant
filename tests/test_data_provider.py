# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 统一数据访问层（data_provider）单元测试

覆盖三级降级逻辑（真实API -> api_cache -> 种子表），并断言 data_source 字段：
- 种子表路径（simulated）：未配置 API Key 时返回种子兜底数据
- 真实 API 路径（real）：命中缓存键后回源并附带 real 标记
- 缓存路径（cache）：命中 api_cache 时不发起真实请求，附带 cache 标记

所有测试均 mock Database 与 httpx，完全离线运行。
"""
import json
from datetime import datetime, timedelta

import city_service_assistant.utils.data_provider as dp


class FakeDatabase:
    """模拟 db.Database：按 one 参数区分返回单行 / 多行"""

    def __init__(self, query_result=None):
        self._query_result = query_result
        self.calls = []

    def query(self, sql, params=None, one=False):
        self.calls.append(("query", sql, params, one))
        if one:
            if isinstance(self._query_result, list):
                return self._query_result[0] if self._query_result else None
            return self._query_result
        if isinstance(self._query_result, list):
            return self._query_result
        return [self._query_result] if self._query_result is not None else []

    def execute(self, sql, params=None):
        self.calls.append(("execute", sql, params))
        return 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _patch_db(monkeypatch, query_result=None):
    """替换 data_provider.Database 为返回固定结果的 FakeDatabase，并返回实例"""
    fake_db = FakeDatabase(query_result)
    monkeypatch.setattr(dp, "Database", lambda: fake_db)
    return fake_db


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ==================== 一、种子表路径（simulated） ====================

def test_get_weather_simulated(monkeypatch):
    """未配置和风 Key：走种子表，返回 (种子行, simulated) 元组"""
    today = _today()
    seed_row = {"city": "北京", "fx_date": today, "weather": "晴",
                "temp_max": "30", "temp_min": "20"}
    fake_db = _patch_db(monkeypatch, seed_row)
    monkeypatch.setattr(dp.config, "QWEATHER_API_KEY", "")

    result = dp.get_weather("北京", date=today)
    assert result["data_source"] == "simulated"
    assert result["city"] == "北京"
    assert result["fx_date"] == today
    # 确认确实走了种子查询
    assert any("weather_data" in c[1] for c in fake_db.calls)


def test_get_air_quality_simulated(monkeypatch):
    """未配置和风 Key：空气质量走种子表"""
    today = _today()
    seed_row = {"city": "北京", "fx_date": today, "aqi": "60", "category": "良"}
    _patch_db(monkeypatch, seed_row)
    monkeypatch.setattr(dp.config, "QWEATHER_API_KEY", "")

    result = dp.get_air_quality("北京", date=today)
    assert result["data_source"] == "simulated"
    assert result["city"] == "北京"
    assert result["aqi"] == "60"


def test_get_traffic_status_simulated(monkeypatch):
    """未配置高德 Key：路况走种子表，返回 dict 且 data_source=simulated"""
    seed_roads = [{"road_name": "长安街", "status": 1, "speed": 35, "congestion_index": 1.1}]
    _patch_db(monkeypatch, seed_roads)
    monkeypatch.setattr(dp.config, "AMAP_KEY", "")

    result = dp.get_traffic_status("北京")
    assert result["data_source"] == "simulated"
    assert result["roads"][0]["road_name"] == "长安街"


def test_get_service_guide_simulated(monkeypatch):
    """政务指南直接读种子表（无外部 API），data_source=simulated"""
    seed_rows = [{"id": 1, "item_name": "户口迁移", "category": "户籍",
                  "department": "公安局", "material_list": "身份证", "process": "1", "text": "..."}]
    _patch_db(monkeypatch, seed_rows)

    result = dp.get_service_guide("户籍")
    assert result["data_source"] == "simulated"
    assert result["items"][0]["category"] == "户籍"


# ==================== 二、真实 API 路径（real） ====================

def test_get_weather_real(monkeypatch):
    """命中真实 API：data_source=real，且结果写入 api_cache"""
    today = _today()

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": "200", "daily": [{
                "fxDate": today, "textDay": "晴", "tempMax": "31", "tempMin": "22",
                "humidity": "40", "pressure": "1010", "vis": "25",
                "windDirDay": "东风", "windScaleDay": "3",
            }]}

    fake_db = _patch_db(monkeypatch, None)  # 无缓存
    monkeypatch.setattr(dp.config, "QWEATHER_API_KEY", "test-key")
    monkeypatch.setattr(dp.httpx, "get", lambda *a, **k: FakeResp())

    result = dp.get_weather("北京", date=today)
    assert result["data_source"] == "real"
    assert result["weather"] == "晴"
    assert result["temp_max"] == "31"
    # 确认已写入 api_cache
    assert any(c[0] == "execute" for c in fake_db.calls)


# ==================== 三、缓存路径（cache） ====================

def test_get_weather_cache_hit(monkeypatch):
    """命中 api_cache：不发起真实请求，data_source=cache"""
    today = _today()
    cached_payload = {"code": "200", "daily": [{
        "fxDate": today, "textDay": "多云", "tempMax": "28", "tempMin": "18",
        "humidity": "50", "pressure": "1008", "vis": "20",
        "windDirDay": "南风", "windScaleDay": "2",
    }]}
    cache_row = {
        "payload_json": json.dumps(cached_payload, ensure_ascii=False),
        "ttl_expire": datetime.now() + timedelta(hours=1),
    }
    _patch_db(monkeypatch, cache_row)
    monkeypatch.setattr(dp.config, "QWEATHER_API_KEY", "test-key")

    def _fail(*a, **k):
        raise AssertionError("命中缓存时不应发起真实 API 请求")

    monkeypatch.setattr(dp.httpx, "get", _fail)

    result = dp.get_weather("北京", date=today)
    assert result["data_source"] == "cache"
    assert result["weather"] == "多云"


def test_fetch_api_cache_expired_ignored(monkeypatch):
    """缓存已过期视为未命中，降级为真实 API 请求"""
    today = _today()
    expired_row = {
        "payload_json": json.dumps({"code": "200", "daily": []}, ensure_ascii=False),
        "ttl_expire": datetime.now() - timedelta(seconds=10),
    }
    _patch_db(monkeypatch, expired_row)
    monkeypatch.setattr(dp.config, "QWEATHER_API_KEY", "test-key")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": "200", "daily": [{
                "fxDate": today, "textDay": "晴", "tempMax": "29", "tempMin": "19",
                "humidity": "45", "pressure": "1009", "vis": "22",
                "windDirDay": "北风", "windScaleDay": "3",
            }]}

    monkeypatch.setattr(dp.httpx, "get", lambda *a, **k: FakeResp())

    result = dp.get_weather("北京", date=today)
    assert result["data_source"] == "real"


# ==================== 四、降级辅助逻辑 ====================

def test_fetch_api_error_returns_none(monkeypatch):
    """真实 API 请求异常时返回 (None, error)，交由上层走种子兜底"""
    _patch_db(monkeypatch, None)
    monkeypatch.setattr(dp.config, "QWEATHER_API_KEY", "test-key")

    class Boom:
        def raise_for_status(self):
            raise RuntimeError("网络不可用")

    monkeypatch.setattr(dp.httpx, "get", lambda *a, **k: Boom())

    payload, mark = dp.fetch_api("qweather", {"city": "北京"}, "http://example.invalid")
    assert payload is None
    assert mark == "error"


def test_hash_deterministic():
    """缓存键哈希对相同参数稳定、对不同参数不同"""
    h1 = dp._hash("qweather", {"city": "北京", "api": "weather/3d"})
    h2 = dp._hash("qweather", {"city": "北京", "api": "weather/3d"})
    h3 = dp._hash("qweather", {"city": "上海", "api": "weather/3d"})
    assert h1 == h2
    assert h1 != h3
