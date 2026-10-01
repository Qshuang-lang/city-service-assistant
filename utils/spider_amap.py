# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 交通/POI 数据采集脚本（高德地图）
采集内容：
  - 实时路况 traffic_status（高德矩形路况接口）
  - 公共设施 POI poi_places（医院/图书馆/公园/政务大厅/学校等）
  - 停车场 parking_lots
写入对应表，API 不可用时由种子数据兜底（simulated）。
"""
from datetime import datetime
from urllib.parse import quote

from city_service_assistant.config import config
from city_service_assistant.create_logger import logger
from city_service_assistant.db import Database
from city_service_assistant.utils.data_provider import AMAP_ADCODES, _city_rect, fetch_api

# POI 类型关键词（用于 place/text 检索并写入 poi_places.poi_type）
POI_TYPES = ["医院", "图书馆", "公园", "政务大厅", "学校", "博物馆"]


def _amap_status(s):
    mapping = {"1": 1, "2": 2, "3": 3, "4": 3}
    return mapping.get(str(s), 1)


def collect_traffic(db: Database, city: str, adcode: str):
    """高德矩形路况：矩形跨度需足够小（约 0.05°）接口才返回道路级数据，
    统一复用 data_provider._city_rect 保证与实时链路一致，避免 INVALID_PARAMS。"""
    bounds = _city_rect(city)
    url = (f"{config.AMAP_HOST}/traffic/status/rectangle?key={config.AMAP_KEY}"
           f"&extensions=all&rectangle={quote(bounds)}")
    payload, mark = fetch_api(
        "amap", {"city": city, "api": "traffic"}, url,
    )
    if not payload or payload.get("status") != "1":
        logger.warning("%s 路况数据无效(%s)，跳过", city, mark)
        return 0
    roads = (payload.get("trafficinfo") or {}).get("roads", [])
    now = datetime.now()
    count = 0
    for r in roads[:20]:
        row = {
            "city": city, "road_name": r.get("name"),
            "status": _amap_status(r.get("status")),
            "speed": r.get("speed"), "congestion_index": r.get("congestion"),
            "update_time": now,
        }
        db.execute(
            """INSERT INTO traffic_status (city, road_name, status, speed, congestion_index, update_time)
               VALUES (%(city)s, %(road_name)s, %(status)s, %(speed)s, %(congestion_index)s, %(update_time)s)
               ON DUPLICATE KEY UPDATE status=VALUES(status), speed=VALUES(speed),
                   congestion_index=VALUES(congestion_index), update_time=VALUES(update_time)""",
            row,
        )
        count += 1
    logger.info("%s 路况入库 %d 条 (%s)", city, count, mark)
    return count


def _place_text(db: Database, city: str, adcode: str, keywords: str):
    """高德 POI 文本搜索，返回原始 pois 列表或 None"""
    url = (f"{config.AMAP_HOST}/place/text?key={config.AMAP_KEY}"
           f"&keywords={quote(keywords)}&city={adcode}&citylimit=true&offset=20")
    payload, mark = fetch_api(
        "amap", {"city": city, "api": "poi", "keywords": keywords}, url,
    )
    if not payload or payload.get("status") != "1":
        logger.warning("%s POI[%s] 无效(%s)", city, keywords, mark)
        return None, mark
    return (payload.get("pois") or []), mark


def collect_poi(db: Database, city: str, adcode: str, force=False):
    count = 0
    for ptype in POI_TYPES:
        pois, mark = _place_text(db, city, adcode, ptype)
        if pois is None:
            continue
        for p in pois[:10]:
            loc = (p.get("location") or "").split(",")
            lng = loc[0] if len(loc) > 1 else None
            lat = loc[1] if len(loc) > 1 else None
            open_time = (p.get("biz_ext") or {}).get("open_time", "") or ""
            if not isinstance(open_time, str):
                open_time = str(open_time)
            row = {
                "city": city, "poi_type": ptype, "name": p.get("name"),
                "address": p.get("address"), "lat": lat, "lng": lng,
                "open_hours": open_time,
                "distance": None,
            }
            db.execute(
                """INSERT INTO poi_places (city, poi_type, name, address, lat, lng, open_hours, distance)
                   VALUES (%(city)s, %(poi_type)s, %(name)s, %(address)s, %(lat)s, %(lng)s, %(open_hours)s, %(distance)s)
                   ON DUPLICATE KEY UPDATE address=VALUES(address), lat=VALUES(lat),
                       lng=VALUES(lng), open_hours=VALUES(open_hours)""",
                row,
            )
            count += 1
    logger.info("%s POI 入库 %d 条 (%s)", city, count, mark if 'mark' in dir() else "skipped")
    return count


def collect_parking(db: Database, city: str, adcode: str):
    pois, mark = _place_text(db, city, adcode, "停车场")
    if pois is None:
        logger.info("%s 停车场数据无效(%s)", city, mark)
        return 0
    count = 0
    for p in pois[:20]:
        loc = (p.get("location") or "").split(",")
        lng = loc[0] if len(loc) > 1 else None
        lat = loc[1] if len(loc) > 1 else None
        open_time = (p.get("biz_ext") or {}).get("open_time", "") or ""
        if not isinstance(open_time, str):
            open_time = str(open_time)
        row = {
            "city": city, "name": p.get("name"), "address": p.get("address"),
            "lat": lat, "lng": lng, "total_spaces": None, "free_spaces": None,
            "open_hours": open_time,
        }
        db.execute(
            """INSERT INTO parking_lots (city, name, address, lat, lng, total_spaces, free_spaces, open_hours)
               VALUES (%(city)s, %(name)s, %(address)s, %(lat)s, %(lng)s, %(total_spaces)s, %(free_spaces)s, %(open_hours)s)
               ON DUPLICATE KEY UPDATE address=VALUES(address), lat=VALUES(lat),
                   lng=VALUES(lng), open_hours=VALUES(open_hours)""",
            row,
        )
        count += 1
    logger.info("%s 停车场入库 %d 条 (%s)", city, count, mark)
    return count


def update_amap(force_update=False, cities: list = None):
    db = Database()
    cities = cities or list(AMAP_ADCODES.keys())
    for city in cities:
        adcode = AMAP_ADCODES.get(city)
        if not adcode:
            continue
        try:
            collect_traffic(db, city, adcode)
            collect_poi(db, city, adcode)
            collect_parking(db, city, adcode)
        except Exception as e:  # noqa: BLE001
            logger.error("%s 高德采集异常: %s", city, e)
    db.close()
    logger.info("高德数据采集完成")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="高德地图数据采集")
    parser.add_argument("--force", action="store_true", help="强制更新")
    parser.add_argument("--cities", nargs="*", default=None, help="指定城市列表")
    args = parser.parse_args()
    update_amap(force_update=args.force, cities=args.cities)
