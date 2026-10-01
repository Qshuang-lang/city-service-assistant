# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - MCP 工具函数单元测试

覆盖三个 MCP 服务暴露的工具函数（mock data_provider / RAG 模块），
断言返回结构与 data_source 字段，验证「数据链路统一走 data_provider」约定：
- weather_server:  get_weather / get_air_quality
- traffic_server:  get_traffic_status / get_transit_routes / get_parking / get_poi
- life_server:     get_service_guide / search_guides（成功 / 失败两种路径）

所有测试均不发起真实网络请求，完全离线运行。
"""
import city_service_assistant.mcp_server.weather_server as ws
import city_service_assistant.mcp_server.traffic_server as ts
import city_service_assistant.mcp_server.life_server as ls


# ==================== 气象 MCP ====================

def test_weather_server_get_weather(monkeypatch):
    """get_weather 工具：透传 data_provider 结果并保留 data_source"""
    monkeypatch.setattr(ws, "_dp_get_weather",
                        lambda city: {"city": city, "weather": "晴", "temp_max": "31",
                                      "data_source": "simulated"})
    result = ws.get_weather("北京")
    assert result["city"] == "北京"
    assert result["weather"] == "晴"
    assert result["data_source"] == "simulated"


def test_weather_server_get_air_quality(monkeypatch):
    """get_air_quality 工具：返回含 aqi 与 data_source 的结构"""
    monkeypatch.setattr(ws, "_dp_get_air_quality",
                        lambda city: {"city": city, "aqi": "50", "category": "优",
                                      "data_source": "simulated"})
    result = ws.get_air_quality("北京")
    assert result["aqi"] == "50"
    assert result["category"] == "优"
    assert result["data_source"] == "simulated"


# ==================== 交通 MCP ====================

def test_traffic_server_get_traffic_status(monkeypatch):
    """get_traffic_status 工具：返回 roads 列表 + data_source"""
    monkeypatch.setattr(ts, "_dp_get_traffic_status",
                        lambda city: {"city": city, "roads": [{"road_name": "长安街"}],
                                      "data_source": "simulated"})
    result = ts.get_traffic_status("北京")
    assert "roads" in result
    assert result["roads"][0]["road_name"] == "长安街"
    assert result["data_source"] == "simulated"


def test_traffic_server_get_transit_routes(monkeypatch):
    """get_transit_routes 工具：支持带 origin/destination 的点对点查询"""
    monkeypatch.setattr(
        ts, "_dp_get_transit_routes",
        lambda city, origin=None, destination=None: {
            "city": city, "routes": [{"line_name": "1号线"}], "data_source": "simulated",
        })
    result = ts.get_transit_routes("北京")
    assert result["data_source"] == "simulated"
    assert result["routes"][0]["line_name"] == "1号线"

    # 带起终点时仍正常透传
    result2 = ts.get_transit_routes("北京", "北京西站", "首都机场T3")
    assert result2["data_source"] == "simulated"


def test_traffic_server_get_parking(monkeypatch):
    """get_parking 工具：返回 items 列表 + data_source"""
    monkeypatch.setattr(ts, "_dp_get_parking",
                        lambda city: {"city": city, "items": [{"name": "中心停车场"}],
                                      "data_source": "simulated"})
    result = ts.get_parking("北京")
    assert result["items"][0]["name"] == "中心停车场"
    assert result["data_source"] == "simulated"


def test_traffic_server_get_poi(monkeypatch):
    """get_poi 工具：透传 poi_type 参数并保留 data_source"""
    monkeypatch.setattr(ts, "_dp_get_poi",
                        lambda city, poi_type: {"city": city, "poi_type": poi_type,
                                                "items": [], "data_source": "simulated"})
    result = ts.get_poi("北京", "医院")
    assert result["poi_type"] == "医院"
    assert result["data_source"] == "simulated"


# ==================== 生活政务 MCP ====================

def test_life_server_get_service_guide(monkeypatch):
    """get_service_guide 工具：透传 data_provider 结果"""
    monkeypatch.setattr(ls, "_dp_get_service_guide",
                        lambda category=None: {"items": [{"item_name": "户口迁移"}],
                                               "data_source": "simulated"})
    result = ls.get_service_guide("户籍")
    assert result["items"][0]["item_name"] == "户口迁移"
    assert result["data_source"] == "simulated"


def test_life_server_search_guides_ok(monkeypatch):
    """search_guides 工具成功路径：data_source=milvus_rag，items 携带检索结果"""
    monkeypatch.setattr(
        ls, "_rag_search_guides",
        lambda query, top_k=3, category=None: {
            "query": query,
            "items": [{"item_name": "户口迁移"}],
            "data_source": "milvus_rag",
            "engine": "milvus_rag",
        })
    result = ls.search_guides("我想办理户口迁移，需要准备什么材料", top_k=3)
    assert result["query"] == "我想办理户口迁移，需要准备什么材料"
    assert result["items"] == [{"item_name": "户口迁移"}]
    assert result["data_source"] == "milvus_rag"
    assert result["engine"] == "milvus_rag"


def test_life_server_search_guides_error(monkeypatch):
    """search_guides 工具失败路径：Milvus 不可用时返回友好提示而非抛出异常"""
    def _boom(*a, **k):
        raise RuntimeError("Milvus 未启动")

    monkeypatch.setattr(ls, "_rag_search_guides", _boom)
    result = ls.search_guides("户口迁移")
    assert result["data_source"] == "error"
    assert "error" in result
    assert "hint" in result
