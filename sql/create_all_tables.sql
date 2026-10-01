DROP DATABASE IF EXISTS csp_db;
CREATE DATABASE csp_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE csp_db;

-- ============ 一、气象类（和风天气） ============
DROP TABLE IF EXISTS weather_data;
CREATE TABLE weather_data (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    city VARCHAR(50) NOT NULL COMMENT '城市名，如 广州',
    fx_date DATE NOT NULL COMMENT '日期（实时数据存当天）',
    weather VARCHAR(50) COMMENT '天气现象，如 多云转晴',
    temp_max INT COMMENT '最高温 ℃',
    temp_min INT COMMENT '最低温 ℃',
    aqi INT COMMENT '空气质量指数 AQI',
    alert_level VARCHAR(16) COMMENT '预警等级，如 蓝色/黄色',
    humidity INT COMMENT '相对湿度 %',
    pressure INT COMMENT '大气压强 hPa',
    vis INT COMMENT '能见度 km',
    wind_dir VARCHAR(20) COMMENT '风向',
    wind_scale VARCHAR(10) COMMENT '风力等级',
    update_time DATETIME COMMENT '数据更新时间',
    UNIQUE KEY unique_city_date (city, fx_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='气象数据表(和风+种子兜底)';

DROP TABLE IF EXISTS air_quality;
CREATE TABLE air_quality (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    city VARCHAR(50) NOT NULL COMMENT '城市名',
    fx_date DATE NOT NULL COMMENT '日期',
    aqi INT COMMENT 'AQI 指数',
    category VARCHAR(20) COMMENT '等级：优/良/轻度污染等',
    pm2p5 INT COMMENT 'PM2.5 μg/m³',
    pm10 INT COMMENT 'PM10 μg/m³',
    o3 INT COMMENT '臭氧 μg/m³',
    no2 INT COMMENT '二氧化氮 μg/m³',
    so2 INT COMMENT '二氧化硫 μg/m³',
    co DECIMAL(4,1) COMMENT '一氧化碳 mg/m³',
    update_time DATETIME COMMENT '更新时间',
    UNIQUE KEY unique_aq (city, fx_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='空气质量表(和风+种子兜底)';

-- ============ 二、交通类（高德地图） ============
DROP TABLE IF EXISTS traffic_status;
CREATE TABLE traffic_status (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    city VARCHAR(50) NOT NULL COMMENT '城市名',
    road_name VARCHAR(100) NOT NULL COMMENT '道路名，如 中山大道',
    status TINYINT COMMENT '路况：1畅通 2缓行 3拥堵',
    speed DECIMAL(5,1) COMMENT '平均速度 km/h',
    congestion_index DECIMAL(4,1) COMMENT '拥堵指数',
    update_time DATETIME COMMENT '更新时间',
    UNIQUE KEY unique_road (city, road_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='实时路况表(高德+种子兜底)';

DROP TABLE IF EXISTS transit_routes;
CREATE TABLE transit_routes (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    city VARCHAR(50) NOT NULL COMMENT '城市名',
    line_name VARCHAR(50) NOT NULL COMMENT '线路名，如 地铁3号线',
    station_name VARCHAR(50) NOT NULL COMMENT '站点名',
    seq_no INT COMMENT '站序',
    transfer_line VARCHAR(50) COMMENT '可换乘线路',
    start_time VARCHAR(10) COMMENT '首班时间 HH:MM',
    end_time VARCHAR(10) COMMENT '末班时间 HH:MM',
    UNIQUE KEY unique_station (city, line_name, station_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公交/地铁线路表(高德+种子兜底)';

DROP TABLE IF EXISTS poi_places;
CREATE TABLE poi_places (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    city VARCHAR(50) NOT NULL COMMENT '城市名',
    poi_type VARCHAR(30) NOT NULL COMMENT 'POI类型：医院/图书馆/公园/政务大厅',
    name VARCHAR(100) NOT NULL COMMENT '设施名称',
    address VARCHAR(200) COMMENT '地址',
    lat DECIMAL(10,6) COMMENT '纬度',
    lng DECIMAL(10,6) COMMENT '经度',
    open_hours VARCHAR(100) COMMENT '开放时间',
    distance INT COMMENT '距当前位置（米）',
    UNIQUE KEY unique_poi (city, poi_type, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公共设施POI表(高德+种子兜底)';

DROP TABLE IF EXISTS parking_lots;
CREATE TABLE parking_lots (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    city VARCHAR(50) NOT NULL COMMENT '城市名',
    name VARCHAR(100) NOT NULL COMMENT '停车场名称',
    address VARCHAR(200) COMMENT '地址',
    lat DECIMAL(10,6) COMMENT '纬度',
    lng DECIMAL(10,6) COMMENT '经度',
    total_spaces INT COMMENT '总车位',
    free_spaces INT COMMENT '剩余车位',
    open_hours VARCHAR(100) COMMENT '开放时间',
    UNIQUE KEY unique_parking (city, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='停车场表(高德+种子兜底)';

-- ============ 三、政务服务类（自建 + Milvus RAG） ============
DROP TABLE IF EXISTS service_guides;
CREATE TABLE service_guides (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    item_name VARCHAR(100) NOT NULL COMMENT '办事事项名',
    category VARCHAR(50) COMMENT '分类：户籍/社保/医保等',
    department VARCHAR(100) COMMENT '办理部门',
    material_list TEXT COMMENT '所需材料清单',
    process TEXT COMMENT '办理流程',
    text TEXT COMMENT '事项全文（供 Milvus 向量化）',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    UNIQUE KEY unique_guide (item_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='政务办事指南表(Milvus RAG 数据源)';

DROP TABLE IF EXISTS complaints;
CREATE TABLE complaints (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    content TEXT NOT NULL COMMENT '投诉/建议内容',
    category VARCHAR(30) COMMENT '分类：交通/卫生/市容/其他',
    contact VARCHAR(50) COMMENT '联系方式',
    status VARCHAR(20) DEFAULT '待处理' COMMENT '状态：待处理/处理中/已办结',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '提交时间',
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='投诉建议工单表';

-- ============ 四、用户与记忆类（自建） ============
DROP TABLE IF EXISTS user_profiles;
CREATE TABLE user_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    user_id VARCHAR(64) NOT NULL DEFAULT 'default' COMMENT '用户标识',
    pref_key VARCHAR(50) NOT NULL COMMENT '偏好键：home_city/commute_route/fav_facility_type',
    pref_value VARCHAR(200) NOT NULL COMMENT '偏好值',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY unique_pref (user_id, pref_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户偏好表';

DROP TABLE IF EXISTS query_history;
CREATE TABLE query_history (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    user_id VARCHAR(64) NOT NULL DEFAULT 'default' COMMENT '用户标识',
    intent_type VARCHAR(30) NOT NULL COMMENT '意图：weather/traffic/poi/guide',
    query_content TEXT NOT NULL COMMENT '查询内容（JSON）',
    response TEXT COMMENT '回复内容',
    query_time DATETIME NOT NULL COMMENT '查询时间',
    INDEX idx_time (query_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='查询历史表';

DROP TABLE IF EXISTS short_term_messages;
CREATE TABLE short_term_messages (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    role VARCHAR(10) NOT NULL COMMENT '角色：user/assistant',
    content TEXT NOT NULL COMMENT '消息内容',
    message_time VARCHAR(10) NOT NULL COMMENT '时间戳 HH:MM:SS',
    message_order INT NOT NULL COMMENT '消息顺序号',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='短期对话记忆表';

DROP TABLE IF EXISTS long_term_memory;
CREATE TABLE long_term_memory (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    user_id VARCHAR(64) NOT NULL DEFAULT 'default' COMMENT '用户标识',
    memory_type VARCHAR(20) COMMENT '类型：preference/important_fact',
    content TEXT NOT NULL COMMENT '记忆内容',
    importance TINYINT DEFAULT 1 COMMENT '重要度 1-5',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='长期记忆表';

-- ============ 五、API 缓存表（三级降级 L2 层） ============
DROP TABLE IF EXISTS api_cache;
CREATE TABLE api_cache (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键',
    source VARCHAR(32) NOT NULL COMMENT '数据源：qweather/amap/qqmap',
    param_hash CHAR(32) NOT NULL COMMENT '数据源+参数 MD5',
    payload_json JSON NOT NULL COMMENT '缓存结果 JSON',
    ttl_expire DATETIME NOT NULL COMMENT '过期时间',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    UNIQUE KEY uk_source_hash (source, param_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='API结果缓存表(三级降级L2)';