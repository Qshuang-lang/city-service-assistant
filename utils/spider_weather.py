# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 气象数据采集脚本（和风天气）
对齐 SmartVoyage 架构 spider_weather.py：
  - 从和风天气拉取各城市 3 天预报 + 实时空气质量
  - 按 24h 判断是否需要更新，写入 weather_data / air_quality
  - 支持 force_update 强制刷新与定时调度
"""
from datetime import datetime, timedelta

from city_service_assistant.config import config
from city_service_assistant.create_logger import logger
from city_service_assistant.db import Database
from city_service_assistant.utils.data_provider import (
    QWEATHER_CITY_CODES, _fetch_air_v1, _parse_air_v1, fetch_api,
)

TZ_DELTA = timedelta(hours=8)  # 北京时间


def get_latest_update_time(db: Database, table: str, city: str):
    row = db.query(
        f"SELECT MAX(update_time) AS latest FROM {table} WHERE city=%s", (city,), one=True)
    return row["latest"] if row and row["latest"] else None


def should_update(latest, force_update=False) -> bool:
    if force_update:
        return True
    if not latest:
        return True
    now = datetime.now() + TZ_DELTA
    latest = latest + TZ_DELTA if latest.tzinfo is None else latest
    return (now - latest.replace(tzinfo=None)).total_seconds() / 3600 >= 24


def collect_weather(db: Database, city: str, code: str):
    """拉取 3 天预报入库 weather_data"""
    url = f"{config.QWEATHER_HOST}/weather/3d?location={code}"
    payload, mark = fetch_api(
        "qweather", {"city": city, "api": "weather/3d", "location": code}, url,
        headers={"X-QW-Api-Key": config.QWEATHER_API_KEY},
    )
    if not payload or payload.get("code") != "200":
        logger.warning("%s 天气数据无效(%s)，跳过", city, mark)
        return 0
    now = datetime.now()
    count = 0
    for d in payload.get("daily", []):
        row = {
            "city": city, "fx_date": d.get("fxDate"),
            "weather": d.get("textDay"), "temp_max": d.get("tempMax"),
            "temp_min": d.get("tempMin"),
            "humidity": d.get("humidity"), "pressure": d.get("pressure"),
            "vis": d.get("vis"), "wind_dir": d.get("windDirDay"),
            "wind_scale": d.get("windScaleDay"), "update_time": now,
        }
        db.execute(
            """INSERT INTO weather_data
               (city, fx_date, weather, temp_max, temp_min, humidity, pressure,
                vis, wind_dir, wind_scale, update_time)
               VALUES (%(city)s, %(fx_date)s, %(weather)s, %(temp_max)s, %(temp_min)s,
                       %(humidity)s, %(pressure)s, %(vis)s, %(wind_dir)s, %(wind_scale)s, %(update_time)s)
               ON DUPLICATE KEY UPDATE weather=VALUES(weather), temp_max=VALUES(temp_max),
                   temp_min=VALUES(temp_min), humidity=VALUES(humidity),
                   pressure=VALUES(pressure), vis=VALUES(vis),
                   wind_dir=VALUES(wind_dir), wind_scale=VALUES(wind_scale),
                   update_time=VALUES(update_time)""",
            row,
        )
        count += 1
    logger.info("%s 天气入库 %d 天 (%s)", city, count, mark)
    return count


def collect_air(db: Database, city: str, code: str):
    """拉取实时空气质量入库 air_quality。

    注意：和风 Web API v7 的 /v7/air/now 已于 2026-06-01 停服（403），
    改走新版 /airquality/v1/daily（需 .env 配置 QWEATHER_AIR_JWT）；
    未配置 JWT 时跳过采集，由种子数据兜底。
    """
    if not config.QWEATHER_AIR_JWT:
        logger.warning("%s 未配置 QWEATHER_AIR_JWT，跳过空气质量采集（由种子兜底）", city)
        return 0
    payload, mark = _fetch_air_v1(city)
    if payload is None:
        logger.warning("%s 空气质量数据无效(%s)，跳过", city, mark)
        return 0
    row = _parse_air_v1(city, payload, datetime.now().strftime("%Y-%m-%d"))
    if row is None:
        logger.warning("%s 空气质量解析失败(%s)，跳过", city, mark)
        return 0
    row["update_time"] = datetime.now()
    db.execute(
        """INSERT INTO air_quality
           (city, fx_date, aqi, category, pm2p5, pm10, o3, no2, so2, co, update_time)
           VALUES (%(city)s, %(fx_date)s, %(aqi)s, %(category)s, %(pm2p5)s, %(pm10)s,
                   %(o3)s, %(no2)s, %(so2)s, %(co)s, %(update_time)s)
           ON DUPLICATE KEY UPDATE aqi=VALUES(aqi), category=VALUES(category),
               pm2p5=VALUES(pm2p5), pm10=VALUES(pm10), o3=VALUES(o3),
               no2=VALUES(no2), so2=VALUES(so2), co=VALUES(co), update_time=VALUES(update_time)""",
        row,
    )
    logger.info("%s 空气质量入库 (%s)", city, mark)
    return 1


def update_weather(force_update=False, cities: list = None):
    db = Database()
    cities = cities or list(QWEATHER_CITY_CODES.keys())
    total_w = total_a = 0
    for city in cities:
        code = QWEATHER_CITY_CODES.get(city)
        if not code:
            continue
        try:
            latest = get_latest_update_time(db, "weather_data", city)
            if should_update(latest, force_update):
                total_w += collect_weather(db, city, code)
            else:
                logger.info("%s 天气已最新，跳过", city)
            latest_a = get_latest_update_time(db, "air_quality", city)
            if should_update(latest_a, force_update):
                total_a += collect_air(db, city, code)
            else:
                logger.info("%s 空气质量已最新，跳过", city)
        except Exception as e:  # noqa: BLE001
            logger.error("%s 气象采集异常，跳过该城市: %s", city, e)
    db.close()
    logger.info("气象采集完成：天气 %d 条、空气质量 %d 条", total_w, total_a)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="和风天气数据采集")
    parser.add_argument("--force", action="store_true", help="强制更新")
    parser.add_argument("--cities", nargs="*", default=None, help="指定城市列表")
    args = parser.parse_args()
    update_weather(force_update=args.force, cities=args.cities)
