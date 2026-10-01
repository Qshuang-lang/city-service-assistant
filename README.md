# 城市公共服务智能助手（City Service Assistant）

一个基于 **LangChain + A2A + MCP + Multi-Agent + RAG** 的多智能体城市公共服务问答系统。总代理识别用户意图后，动态调度天气、交通、生活政务三个领域子代理，子代理通过 A2A 协议协作、以 MCP 工具链对接外部能力，数据层采用"真实 API → 缓存 → 种子数据"三级降级，开箱即跑，配置 API Key 后自动切换真实数据。

## 功能一览

| 领域 | 子代理 | 能力 | 数据表 |
| --- | --- | --- | --- |
| 气象环境 | WeatherEnvAssistant | 天气查询、空气质量、预警、湿度气压 | weather_data / air_quality |
| 交通出行 | TrafficAssistant | 实时路况、地铁公交线路、停车位查询 | traffic_status / transit_routes / parking_lots |
| 生活政务 | LifeServiceAssistant | 附近 POI（医院/公园/学校等）、办事指南、投诉建议 | poi_places / service_guides / complaints |

## 架构

```
用户 / CLI / Web
      │
      ▼
API Server (FastAPI :8080)  ── 意图识别 + ChatService
      │ A2A (HTTP JSON-RPC)
      ├── weather_server  :5005  ── MCP(stdio) ── 和风天气 API
      ├── traffic_server  :5006  ── MCP(stdio) ── 高德地图 API
      └── life_server     :5007  ── MCP(stdio) ── MySQL 业务数据 / RAG(政务指南)
                     │
                     ▼
            MySQL (city_service_db)  ← 采集脚本写入真实数据 + 种子兜底
```

- **A2A**：总代理与子代理之间采用 A2A 协议通信（a2a-sdk）。
- **MCP**：子代理以 MCP stdio 子进程方式对外暴露工具能力。
- **RAG**：政务办事指南支持向量检索（Milvus 可选；未启动时自动降级为 SQL 关键词检索）。

## 目录结构

```
city_service_assistant/
├── api_server.py            # FastAPI 总代理（HTTP 入口）
├── chat_service.py          # 意图识别 + A2A 子代理调度
├── config.py                # 配置（.env）
├── init_db.py               # 建库建表 + 导入种子（--fetch 可选拉取真实数据）
├── memory.py                # 对话记忆 / 用户画像 / 查询历史（MySQL 持久化）
├── main.py                  # CLI 客户端
├── a2a_server/              # 三个 A2A 子代理（weather/traffic/life）
├── mcp_server/              # 三个 MCP 服务（weather/traffic/life）
├── rag/                     # 政务指南 RAG 检索
├── utils/
│   ├── data_provider.py     # 统一数据访问层（real → cache → simulated）
│   ├── spider_weather.py    # 和风天气采集脚本
│   └── spider_amap.py       # 高德地图采集脚本（路况/POI/停车场）
├── scripts/
│   ├── start_all.py         # 一键启动 4 个进程
│   ├── stop_all.py          # 一键停止
│   └── a2a_smoke.py         # A2A 冒烟测试
├── sql/
│   ├── create_all_tables.sql  # 建库建表（13 张表）
│   ├── insert_seed_data.sql   # 基础种子数据
│   └── seed_enhance.sql       # 种子数据增强补丁（init_db 自动应用）
├── static/index.html        # 简单 Web 演示页
└── tests/                   # 单元测试
```

## 环境要求

- Python 3.11+
- MySQL 8.0（推荐 phpStudy 等集成环境）
- 可选：Docker + Milvus（启用政务指南向量检索；未启动时自动降级，不影响主流程）

## 快速开始

```bash
# 1. 克隆并安装依赖
git clone <your-repo-url>
cd city_service_assistant
python -m venv venv
venv\Scripts\activate            # Windows；Linux/macOS: source venv/bin/activate
pip install -r requirements.txt

# 2. 配置 .env
copy .env.example .env          # Windows；Linux: cp .env.example .env
# 编辑 .env，填入 MySQL 密码与第三方 API Key（见下方「数据与 Key 说明」）

# 3. 初始化数据库（建库建表 + 导入种子数据）
python -m city_service_assistant.init_db
# 可选：初始化后立即拉取真实 API 数据
python -m city_service_assistant.init_db --fetch

# 4. 一键启动全部服务（weather 5005 / traffic 5006 / life 5007 / api 8080）
python -m city_service_assistant.scripts.start_all
# 另开终端：python -m city_service_assistant.scripts.stop_all 可统一停止

# 5. 验证
#   浏览器打开 http://127.0.0.1:8080 或直接调用：
#   curl "http://127.0.0.1:8080/api/agents"
#   curl -X POST "http://127.0.0.1:8080/api/chat" -H "Content-Type: application/json" -d '{"message":"武汉明天天气怎么样"}'
#   也可用 CLI：
#   python -m city_service_assistant.main
```

## 数据与 Key 说明

### 三级数据降级策略

所有业务数据统一经 `utils/data_provider.py` 获取，自动按以下顺序降级：

1. **real**：调用真实第三方 API（和风天气 / 高德地图）；
2. **cache**：命中 MySQL `api_cache` 缓存（TTL 内）；
3. **simulated**：以上均不可用时，回落到 `sql/insert_seed_data.sql` 预置的种子数据。

因此：**没有 Key 也能完整跑通全部功能**（展示的是种子数据）；配置 Key 并运行采集脚本后，自动获得各城市真实数据。

### 需要的 API Key（.env）

| 变量 | 用途 | 是否必填 |
| --- | --- | --- |
| DASHSCOPE_API_KEY | 通义千问大模型（回答组织） | 必填 |
| MYSQL_PASSWORD | 本地 MySQL 密码 | 必填 |
| QWEATHER_API_KEY | 和风天气（3 天预报） | 建议 |
| AMAP_KEY | 高德地图（路况 / POI / 停车场） | 建议 |
| QWEATHER_AIR_JWT | 和风空气质量新版接口 JWT | 可选 |

> 和风空气质量：Web API v7 的 `/v7/air/now` 已于 2026-06-01 停服（403），新版接口为 `/airquality/v1/daily`，需在控制台生成 JWT 并开通空气质量订阅；未配置时空气质量由种子数据兜底。
>
> 高德路况：`traffic/status/rectangle` 接口在部分免费 Key 下返回 `INVALID_PARAMS`（接口权限限制），此时实时路况由种子数据兜底；POI / 停车场不受影响。

### 采集脚本

```bash
# 拉取 10 个城市 3 天天气预报（真实数据）
python -m city_service_assistant.utils.spider_weather --force
# 指定城市
python -m city_service_assistant.utils.spider_weather --force --cities 北京 武汉

# 拉取高德路况 / POI / 停车场
python -m city_service_assistant.utils.spider_amap
python -m city_service_assistant.utils.spider_amap --cities 武汉
```

支持城市：北京 / 上海 / 广州 / 杭州 / 南京 / 武汉 / 成都 / 深圳 / 西安 / 重庆。

### 种子数据覆盖

> init_db 自动执行 `insert_seed_data.sql` + `seed_enhance.sql`，以下为合并后的完整种子量；采集脚本运行后，对应真实数据会覆盖/补充到各表。

| 表 | 种子量 | 说明 |
| --- | --- | --- |
| weather_data | 30 | 10 城市 × 3 天（近期预报） |
| air_quality | 30 | 10 城市 × 3 天 |
| traffic_status | 48 | 10 城市主要道路路况 |
| transit_routes | 138 | 10 城市地铁线路站点 |
| poi_places | 51 | 医院/图书馆/公园/政务大厅/学校/博物馆 |
| parking_lots | 24 | 停车场信息 |
| service_guides | 35 | 政务办事指南（RAG 语料，覆盖 15+ 类事项） |
| user_profiles | 4 | 示例用户画像 |

## 端口一览

| 服务 | 端口 | 配置项 |
| --- | --- | --- |
| API Server | 8080 | API_SERVER_PORT |
| MCP weather / traffic / life | 8002 / 8001 / 8003 | MCP_*_PORT |
| A2A weather / traffic / life | 5005 / 5006 / 5007 | A2A_*_PORT |

端口被占用时可在 `.env` 中覆盖，例如 `API_SERVER_PORT=8090`。

## 测试

```bash
python -m pytest tests -v
```

## 已知说明

- Milvus 未启动时，政务指南检索自动降级为 SQL 关键词匹配，功能不受影响；
- 系统代理开启时，采集与调度均绕过系统代理直连（`trust_env=False`），避免本地代理导致 TLS / 502 异常；
- `complaints` 表初始为空（用户提交投诉后写入），属预期行为。
