# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 统一数据访问层（三级降级）
链路：真实API(real) -> MySQL api_cache(cache) -> 种子表(simulated)
每次返回均附带 data_source 字段标注数据来源。
"""
import hashlib
import json
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

from city_service_assistant.config import config
from city_service_assistant.create_logger import logger
from city_service_assistant.db import Database

# 各业务默认 TTL（秒）：天气/路况短、POI/线路长
DEFAULT_TTL = {
    "qweather": 3600,     # 1 小时
    "amap": 300,          # 5 分钟（路况实时性高）
}

# 和风城市代码（用于真实 API，若用户已配置则优先使用）
QWEATHER_CITY_CODES = {
    "北京": "101010100", "上海": "101020100", "广州": "101280101",
    "杭州": "101210101", "南京": "101190101", "武汉": "101200101",
    "成都": "101270101", "深圳": "101280601", "西安": "101110101",
    "重庆": "101040100",
}
# 高德 adcode
AMAP_ADCODES = {
    "北京": "110000", "上海": "310000", "广州": "440100",
    "杭州": "330100", "南京": "320100", "武汉": "420100",
    "成都": "510100", "深圳": "440300", "西安": "610100",
    "重庆": "500100",
}


def _hash(source, params: dict) -> str:
    raw = json.dumps(params, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(f"{source}|{raw}".encode("utf-8")).hexdigest()


def _read_cache(db: Database, source: str, param_hash: str):
    row = db.query(
        "SELECT payload_json, ttl_expire FROM api_cache "
        "WHERE source=%s AND param_hash=%s LIMIT 1",
        (source, param_hash), one=True,
    )
    if not row:
        return None
    expire = row["ttl_expire"]
    if expire < datetime.now():
        return None  # 已过期，视为未命中
    return json.loads(row["payload_json"])


def _write_cache(db: Database, source: str, param_hash: str, payload: dict, ttl_seconds: int):
    db.execute(
        "INSERT INTO api_cache (source, param_hash, payload_json, ttl_expire) "
        "VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE payload_json=VALUES(payload_json), "
        "ttl_expire=VALUES(ttl_expire), create_time=CURRENT_TIMESTAMP",
        (source, param_hash, json.dumps(payload, ensure_ascii=False),
         datetime.now() + timedelta(seconds=ttl_seconds)),
    )


def fetch_api(source: str, params: dict, url: str, headers: dict = None, timeout: int = 8):
    """
    带缓存的 API 请求。
    返回 (payload, source_mark)，source_mark 为 real / cache / error
    """
    param_hash = _hash(source, params)
    ttl = DEFAULT_TTL.get(source, 1800)
    try:
        db = Database()
    except Exception as e:  # noqa: BLE001
        logger.warning("连接数据库失败，跳过缓存直连 API: %s", e)
        db = None

    if db is not None:
        try:
            cached = _read_cache(db, source, param_hash)
            if cached is not None:
                return cached, "cache"
        except Exception as e:  # noqa: BLE001
            logger.warning("读取 api_cache 失败: %s", e)

    try:
        # 注意：真实请求参数应拼进 url；params 仅作缓存键，切勿传给 httpx
        # trust_env=False：绕过系统代理直连，避免本地代理转发导致 TLS/连接异常
        resp = httpx.get(url, headers=headers or {}, timeout=timeout, trust_env=False)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("API 请求失败 [%s] %s: %s", source, url, e)
        return None, "error"

    if db is not None:
        try:
            _write_cache(db, source, param_hash, payload, ttl)
        except Exception as e:  # noqa: BLE001
            logger.warning("写入 api_cache 失败: %s", e)
    return payload, "real"


# ------------------------------------------------------------------
# 一、气象（和风天气）
# ------------------------------------------------------------------
def get_weather(city: str, date: str = None) -> dict:
    """获取指定城市天气。返回 {data, data_source}"""
    date = date or datetime.now().strftime("%Y-%m-%d")
    payload, mark = None, "simulated"
    code = QWEATHER_CITY_CODES.get(city)
    if code and config.QWEATHER_API_KEY:
        url = f"{config.QWEATHER_HOST}/weather/3d?location={code}"
        payload, mark = fetch_api(
            "qweather", {"city": city, "api": "weather/3d", "location": code},
            url, headers={"X-QW-Api-Key": config.QWEATHER_API_KEY},
        )
    if payload and payload.get("code") == "200":
        daily = payload.get("daily") or []
        for d in daily:
            if d.get("fxDate") == date:
                return {
                    "city": city, "fx_date": date, "weather": d.get("textDay"),
                    "temp_max": d.get("tempMax"), "temp_min": d.get("tempMin"),
                    "humidity": d.get("humidity"), "pressure": d.get("pressure"),
                    "vis": d.get("vis"), "wind_dir": d.get("windDirDay"),
                    "wind_scale": d.get("windScaleDay"),
                    "data_source": mark,
                }
    # 种子兜底（优先当天，其次最近日期；统一返回 dict，避免元组导致 MCP 序列化崩溃）
    return _seed_weather_fallback(city, date)


def get_weather_forecast(city: str, days: int = 3) -> dict:
    """获取城市未来 days 天逐日天气预报（默认 3 天）。

    解决"近三日/未来几天天气"这类多日查询：真实接口 weather/3d 一次返回
    今天起 3 天（缓存可复用），种子兜底则按日期降序取最近 days 天。
    返回 {"city", "days": [...], "data_source"}。
    """
    days = max(1, min(int(days), 7))
    code = QWEATHER_CITY_CODES.get(city)
    payload, mark = None, "simulated"
    if code and config.QWEATHER_API_KEY:
        url = f"{config.QWEATHER_HOST}/weather/3d?location={code}"
        payload, mark = fetch_api(
            "qweather", {"city": city, "api": "weather/3d", "location": code}, url,
            headers={"X-QW-Api-Key": config.QWEATHER_API_KEY},
        )
    if payload and payload.get("code") == "200":
        daily = (payload.get("daily") or [])[:days]
        items = [{
            "fx_date": d.get("fxDate"), "weather": d.get("textDay"),
            "temp_max": d.get("tempMax"), "temp_min": d.get("tempMin"),
            "humidity": d.get("humidity"), "wind_dir": d.get("windDirDay"),
            "wind_scale": d.get("windScaleDay"), "uv_index": d.get("uvIndex"),
        } for d in daily]
        return {"city": city, "days": items, "data_source": mark}
    # 种子兜底：按日期降序取最近 days 天（避免"近三日"查不到）
    rows = _seed_rows(
        "weather_data", city=city,
        cols=["fx_date", "weather", "temp_max", "temp_min", "humidity", "wind_dir", "wind_scale"],
    )
    rows = sorted(rows, key=lambda r: str(r.get("fx_date")), reverse=True)[:days]
    items = [{
        "fx_date": str(r.get("fx_date")), "weather": r.get("weather"),
        "temp_max": r.get("temp_max"), "temp_min": r.get("temp_min"),
        "humidity": r.get("humidity"), "wind_dir": r.get("wind_dir"),
        "wind_scale": r.get("wind_scale"),
    } for r in rows]
    return {"city": city, "days": items, "data_source": "simulated"}


def get_air_quality(city: str, date: str = None) -> dict:
    """获取指定城市空气质量。

    数据链路（三级降级）：
        1. 新版和风空气质量 API（/airquality/v1/daily，需 .env 配置 QWEATHER_AIR_JWT）→ real
        2. api_cache（MySQL）→ cache
        3. 种子表 air_quality（按最近日期）→ simulated
    """
    date = date or datetime.now().strftime("%Y-%m-%d")
    # 1) 新版空气质量 API（JWT 认证；未配置 JWT 或调用失败时走缓存/种子）
    payload, mark = _fetch_air_v1(city)
    if payload is not None:
        row = _parse_air_v1(city, payload, date)
        if row is not None:
            return row
    # 2) 老接口已废弃（403），仅当 .env 仍配置旧 key 时尝试，兼容历史配置
    code = QWEATHER_CITY_CODES.get(city)
    if code and config.QWEATHER_API_KEY and not config.QWEATHER_AIR_JWT:
        url = f"{config.QWEATHER_HOST}/air/now?location={code}"
        payload, mark = fetch_api(
            "qweather", {"city": city, "api": "air/now", "location": code}, url,
            headers={"X-QW-Api-Key": config.QWEATHER_API_KEY},
        )
        if payload and payload.get("code") == "200":
            now = payload.get("now") or {}
            return {
                "city": city, "fx_date": date, "aqi": now.get("aqi"),
                "category": now.get("category"), "pm2p5": now.get("pm2p5"),
                "pm10": now.get("pm10"), "o3": now.get("o3"),
                "no2": now.get("no2"), "so2": now.get("so2"),
                "co": now.get("co"), "data_source": mark,
            }
    # 3) 种子兜底：优先当天，其次最近日期（避免空返回导致上层崩溃）
    return _seed_air_fallback(city, date)


# ------------------------------------------------------------------
# 二、交通（高德地图）
# ------------------------------------------------------------------
def get_traffic_status(city: str) -> dict:
    """获取城市路况。返回 {roads: [...], data_source}"""
    adcode = AMAP_ADCODES.get(city)
    if adcode and config.AMAP_KEY:
        # 高德矩形路况：矩形跨度需较小且需 extensions=all 才能返回道路级数据
        rect = _city_rect(city)
        url = (f"{config.AMAP_HOST}/traffic/status/rectangle?key={config.AMAP_KEY}"
               f"&extensions=all&rectangle={quote(rect)}")
        payload, mark = fetch_api(
            "amap", {"city": city, "api": "traffic"}, url,
        )
        if payload and payload.get("status") == "1":
            roads = [
                {
                    "road_name": r.get("name"), "status": _amap_status(r.get("status")),
                    "speed": r.get("speed"), "congestion_index": r.get("congestion"),
                }
                for r in (payload.get("trafficinfo") or {}).get("roads", [])
            ][:20]
            return {"city": city, "roads": roads, "data_source": mark}
    # 种子兜底
    return {"city": city, "roads": _seed_roads(city), "data_source": "simulated"}


def get_transit_routes(city: str, origin: str = None, destination: str = None) -> dict:
    """获取城市公交/地铁线路；可选 origin/destination 做点对点换乘查询。

    返回 {routes: [...]}（城市线路）或 {plan: [...]}（换乘方案）+ data_source
    """
    rows = _seed_rows(
        "transit_routes", city=city,
        cols=["line_name", "station_name", "seq_no", "transfer_line", "start_time", "end_time"],
    )
    if origin and destination:
        plan = _build_transit_plan(rows, origin, destination)
        return {"city": city, "plan": plan, "data_source": "simulated"}
    return {"city": city, "routes": rows, "data_source": "simulated"}


def _build_transit_plan(rows, origin: str, destination: str) -> dict:
    """根据线路种子表构建 起点->终点 换乘方案（站点名归一化匹配）。

    种子数据站点有限，匹配不到时返回 matched=False 的友好降级信息，
    避免上层 LLM 因工具参数校验失败而丢数据。
    """
    import re

    def norm(s: str) -> str:
        s = re.sub(r"(站|T[123])$", "", (s or "").strip())
        return s

    o_norm, d_norm = norm(origin), norm(destination)
    station_lines = {}
    city_lines = []
    for r in rows:
        city_lines.append(r["line_name"])
        station_lines.setdefault(norm(r["station_name"]), []).append(r["line_name"])
    o_lines = station_lines.get(o_norm) or station_lines.get(origin.strip())
    d_lines = station_lines.get(d_norm) or station_lines.get(destination.strip())
    unique_lines = sorted(set(city_lines))
    if not o_lines or not d_lines:
        return {
            "matched": False,
            "message": (
                f"暂未匹配到包含起点「{origin}」或终点「{destination}」的地铁/公交站点记录。"
                f"当前可提供的线路：{('、'.join(unique_lines)) or '无'}。"
                "建议使用地铁换乘、公交或出租车出行，具体可拨打 12345 交通服务热线咨询。"
            ),
            "city_lines": unique_lines,
        }
    common = set(o_lines) & set(d_lines)
    if common:
        line = sorted(common)[0]
        plan = [{"type": "直达", "line": line, "origin": origin, "destination": destination}]
    else:
        plan = [{
            "type": "换乘",
            "line": o_lines[0], "origin": origin,
            "transfer_to": d_lines[0], "destination": destination,
            "note": "请在可换乘站点换乘至目标线路",
        }]
    return {"matched": True, "origin": origin, "destination": destination, "plan": plan}


def get_poi(city: str, poi_type: str) -> dict:
    """获取公共设施 POI。返回 {items: [...], data_source}"""
    adcode = AMAP_ADCODES.get(city)
    if adcode and config.AMAP_KEY:
        url = (f"{config.AMAP_HOST}/place/text?key={config.AMAP_KEY}"
               f"&keywords={quote(poi_type)}&city={adcode}&citylimit=true&offset=20")
        payload, mark = fetch_api(
            "amap", {"city": city, "api": "poi", "poi_type": poi_type}, url,
        )
        if payload and payload.get("status") == "1":
            items = []
            for p in (payload.get("pois") or [])[:20]:
                items.append({
                    "name": p.get("name"), "address": p.get("address"),
                    "lat": p.get("location").split(",")[1] if p.get("location") else None,
                    "lng": p.get("location").split(",")[0] if p.get("location") else None,
                    "open_hours": (p.get("biz_ext") or {}).get("open_time", ""),
                })
            return {"city": city, "poi_type": poi_type, "items": items, "data_source": mark}
    rows = _seed_rows("poi_places", city=city, poi_type=poi_type,
                      cols=["name", "address", "lat", "lng", "open_hours", "distance"])
    return {"city": city, "poi_type": poi_type, "items": rows, "data_source": "simulated"}


def get_parking(city: str) -> dict:
    """获取停车场。返回 {items: [...], data_source}"""
    adcode = AMAP_ADCODES.get(city)
    if adcode and config.AMAP_KEY:
        url = (f"{config.AMAP_HOST}/place/text?key={config.AMAP_KEY}"
               f"&keywords={quote('停车场')}&city={adcode}&citylimit=true&offset=20")
        payload, mark = fetch_api(
            "amap", {"city": city, "api": "parking"}, url,
        )
        if payload and payload.get("status") == "1":
            items = []
            for p in (payload.get("pois") or [])[:20]:
                items.append({
                    "name": p.get("name"), "address": p.get("address"),
                    "lat": p.get("location").split(",")[1] if p.get("location") else None,
                    "lng": p.get("location").split(",")[0] if p.get("location") else None,
                    "total_spaces": None, "free_spaces": None,
                    "open_hours": (p.get("biz_ext") or {}).get("open_time", ""),
                })
            return {"city": city, "items": items, "data_source": mark}
    rows = _seed_rows("parking_lots", city=city,
                      cols=["name", "address", "lat", "lng", "total_spaces", "free_spaces", "open_hours"])
    return {"city": city, "items": rows, "data_source": "simulated"}


# ------------------------------------------------------------------
# 三、政务服务（自建 + RAG 数据源，无外部 API，直接读种子表）
# ------------------------------------------------------------------
def get_service_guide(category: str = None) -> dict:
    with Database() as db:
        if category:
            rows = db.query(
                "SELECT id, item_name, category, department, material_list, process, text "
                "FROM service_guides WHERE category=%s ORDER BY id", (category,))
        else:
            rows = db.query(
                "SELECT id, item_name, category, department, material_list, process, text "
                "FROM service_guides ORDER BY id")
    return {"items": rows, "data_source": "simulated"}


# ------------------------------------------------------------------
# 种子兜底辅助
# ------------------------------------------------------------------
def _seed_latest(table, cols=None, **conds):
    """按城市取种子表最近日期的一行（防止种子表只有历史日期时精确匹配为空）。"""
    with Database() as db:
        select_cols = ", ".join(f"`{c}`" for c in cols) if cols else "*"
        where = " AND ".join(f"`{k}`=%s" for k in conds) if conds else "1=1"
        row = db.query(
            f"SELECT {select_cols} FROM {table} WHERE {where} "
            f"ORDER BY `fx_date` DESC, id DESC LIMIT 1",
            list(conds.values()), one=True,
        )
    return row or {}


def _seed_weather_fallback(city: str, date: str) -> dict:
    row = _seed_one("weather_data", city=city, fx_date=date)
    if not row:
        row = _seed_latest("weather_data", city=city)
    row = dict(row)
    row.setdefault("fx_date", date)
    row["data_source"] = "simulated"
    return row


def _seed_air_fallback(city: str, date: str) -> dict:
    row = _seed_one("air_quality", city=city, fx_date=date)
    if not row:
        row = _seed_latest("air_quality", city=city)
    row = dict(row)
    row.setdefault("fx_date", date)
    row["data_source"] = "simulated"
    return row


def _seed_one(table, **conds):
    with Database() as db:
        where = " AND ".join(f"`{k}`=%s" for k in conds)
        row = db.query(f"SELECT * FROM {table} WHERE {where} LIMIT 1",
                       list(conds.values()), one=True)
    return row or {}


def _seed_rows(table, cols=None, **conds):
    with Database() as db:
        select_cols = ", ".join(f"`{c}`" for c in cols) if cols else "*"
        where = " AND ".join(f"`{k}`=%s" for k in conds) if conds else "1=1"
        rows = db.query(f"SELECT {select_cols} FROM {table} WHERE {where} ORDER BY id LIMIT 20",
                        list(conds.values()))
    return rows


def _seed_roads(city: str):
    rows = _seed_rows("traffic_status", city=city,
                      cols=["road_name", "status", "speed", "congestion_index"])
    return rows


# 各城市主城区近似矩形（左下;右上），跨度需较小（约0.05°）否则高德返回 INVALID_PARAMS
_CITY_RECTS = {
    "北京": "116.35,39.87;116.40,39.92",
    "上海": "121.45,31.20;121.50,31.25",
    "广州": "113.25,23.10;113.30,23.15",
    "杭州": "120.12,30.24;120.17,30.29",
    "南京": "118.75,32.02;118.80,32.07",
    "武汉": "114.28,30.57;114.33,30.62",
    "成都": "104.03,30.64;104.08,30.69",
    "深圳": "114.03,22.52;114.08,22.57",
    "西安": "108.92,34.23;108.97,34.28",
    "重庆": "106.53,29.54;106.58,29.59",
}


def _city_rect(city: str) -> str:
    return _CITY_RECTS.get(city, "116.0,39.0;117.0,40.0")


# 新版空气质量 API（Web API v1）：GET /airquality/v1/daily/{lat}/{lon}
# 认证：Authorization: Bearer <JWT>（QWEATHER_AIR_JWT）
# 返回结构：{"metadata": {...}, "days": [{forecastStartTime, indexes[], pollutants[]}]}
#   indexes[].code == "qaqi" 为中国 AQI 指数；pollutants[] 含 pm2p5/pm10/o3/no2/so2/co 浓度
_QW_AQI_LEVEL_CN = {
    "1": "优", "2": "良", "3": "轻度污染",
    "4": "中度污染", "5": "重度污染", "6": "严重污染",
}
_QW_AIR_POLLUTANT_CN = {
    "pm2p5": "PM2.5", "pm10": "PM10", "o3": "O3",
    "no2": "NO2", "so2": "SO2", "co": "CO",
}


def _fetch_air_v1(city: str):
    """调用新版和风空气质量接口；未配置 JWT 或调用失败返回 (None, 'error')。"""
    if not config.QWEATHER_AIR_JWT:
        return None, "error"
    rect = _CITY_RECTS.get(city)
    if not rect:
        return None, "error"
    lng1, lat1, lng2, lat2 = [float(x) for x in rect.replace(";", ",").split(",")]
    lat, lng = round((lat1 + lat2) / 2, 2), round((lng1 + lng2) / 2, 2)
    base = config.QWEATHER_HOST[:-3] if config.QWEATHER_HOST.endswith("/v7") else config.QWEATHER_HOST
    url = f"{base}/airquality/v1/daily/{lat}/{lng}"
    return fetch_api(
        "qweather", {"city": city, "api": "airquality/v1/daily", "lat": lat, "lng": lng},
        url, headers={"Authorization": f"Bearer {config.QWEATHER_AIR_JWT}"},
    )


def _parse_air_v1(city: str, payload: dict, date: str) -> dict:
    """解析新版空气质量返回，取其当天 QAqi；解析失败返回 None。"""
    days = payload.get("days") or []
    if not days:
        return None
    day = days[0]
    indexes = {i.get("code"): i for i in day.get("indexes") or []}
    qaqi = indexes.get("qaqi")
    if not qaqi:
        return None
    pollutants = {}
    for p in day.get("pollutants") or []:
        code = p.get("code")
        if code:
            val = p.get("concentration")
            if val is None:
                val = p.get("value")
            pollutants[code] = val
    health = (qaqi.get("health") or {})
    advice = (health.get("advice") or {}).get("generalPopulation")
    return {
        "city": city, "fx_date": date,
        "aqi": qaqi.get("aqi"),
        "category": _QW_AQI_LEVEL_CN.get(str(qaqi.get("level")), qaqi.get("category")),
        "pm2p5": pollutants.get("pm2p5"), "pm10": pollutants.get("pm10"),
        "o3": pollutants.get("o3"), "no2": pollutants.get("no2"),
        "so2": pollutants.get("so2"), "co": pollutants.get("co"),
        "health_advice": advice,
        "data_source": "real",
    }


def _amap_status(s):
    """高德 status: 0未知 1畅通 2缓行 3拥堵 4严重拥堵 -> 1/2/3"""
    mapping = {"1": 1, "2": 2, "3": 3, "4": 3}
    return mapping.get(str(s), 1)


if __name__ == "__main__":
    for c in ["北京", "广州"]:
        w = get_weather(c)
        logger.info("%s 天气: %s", c, w)
        a = get_air_quality(c)
        logger.info("%s 空气质量: %s", c, a)
