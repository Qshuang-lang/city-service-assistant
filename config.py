"""
城市公共服务智能助手 - 配置模块
集中管理所有配置项，从 .env 文件读取
"""
import os
from dotenv import load_dotenv

# 加载环境变量
# 注意：显式指定 .env 绝对路径，避免 -m 模块运行 / 直接运行 .py 时
# find_dotenv 查找路径不一致导致加载失败（踩坑记录）
_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_ENV_FILE, override=False)


class Config:
    """系统配置类"""

    # ========== 大模型配置 ==========
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
    LLM_MODEL = "qwen-plus"  # 通义千问模型
    LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # ========== 第三方 API 配置 ==========
    # 和风天气（自动补全 /v7 路径，兼容多种配置写法）
    QWEATHER_API_KEY = os.getenv("QWEATHER_API_KEY", "")
    _qw_host = os.getenv("QWEATHER_HOST", "https://devapi.qweather.com/v7").rstrip("/")
    QWEATHER_HOST = _qw_host if _qw_host.endswith("/v7") else _qw_host + "/v7"
    # 新版空气质量 API（Web API v1）JWT 认证 Token。
    # 说明：和风 Web API v7 的 /v7/air/now 已于 2026-06-01 全面停服（返回 403 Deprecated），
    # 新版接口为 /airquality/v1/daily/{lat}/{lon}，采用 Authorization: Bearer <JWT> 认证。
    # 到和风控制台「个人中心-身份认证/API Key」生成 JWT 并开通空气质量订阅后填入即可启用。
    QWEATHER_AIR_JWT = os.getenv("QWEATHER_AIR_JWT", "")

    # 高德地图
    AMAP_KEY = os.getenv("AMAP_KEY", "")
    AMAP_HOST = "https://restapi.amap.com/v3"

    # 腾讯地图（备用）
    QQ_MAP_KEY = os.getenv("QQ_MAP_KEY", "")
    QQ_MAP_HOST = "https://apis.map.qq.com/ws"

    # ========== MySQL 数据库配置 ==========
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "csp_db")

    # ========== Milvus 向量数据库配置 ==========
    MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
    MILVUS_PORT = int(os.getenv("MILVUS_PORT", 19530))

    # ========== 日志配置 ==========
    LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "app.log")

    # ========== 服务端口配置 ==========
    API_SERVER_PORT = int(os.getenv("API_SERVER_PORT", 8080))
    MCP_WEATHER_PORT = int(os.getenv("MCP_WEATHER_PORT", 8002))
    MCP_TRAFFIC_PORT = int(os.getenv("MCP_TRAFFIC_PORT", 8001))
    MCP_LIFE_PORT = int(os.getenv("MCP_LIFE_PORT", 8003))
    A2A_WEATHER_PORT = int(os.getenv("A2A_WEATHER_PORT", 5005))
    A2A_TRAFFIC_PORT = int(os.getenv("A2A_TRAFFIC_PORT", 5006))
    A2A_LIFE_PORT = int(os.getenv("A2A_LIFE_PORT", 5007))

    # ========== 意图路由配置 ==========
    # 意图到子代理的映射
    INTENT_AGENT_MAP = {
        # 气象环境意图
        "weather": "WeatherEnvAssistant",
        "air_quality": "WeatherEnvAssistant",
        "weather_alert": "WeatherEnvAssistant",
        # 交通出行意图
        "traffic_status": "TrafficAssistant",
        "transit": "TrafficAssistant",
        "geocode": "TrafficAssistant",
        "parking": "TrafficAssistant",
        # 生活政务意图（agent 名与 a2a_server/life_server.py 的 agent_name=LifeServiceAssistant 对齐）
        "poi": "LifeServiceAssistant",
        "service_guide": "LifeServiceAssistant",
        "complaint": "LifeServiceAssistant",
    }

    # 独立意图（不需要复杂规划，直接执行）
    INDEPENDENT_INTENTS = {
        "weather", "air_quality", "weather_alert",
        "traffic_status", "transit", "geocode", "parking",
        "poi", "service_guide",
    }


# 全局配置实例
config = Config()
