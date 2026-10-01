# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 日志模块
对齐 SmartVoyage 架构中的 create_logger.py，输出到控制台 + logs/app.log
"""
import logging
import os

from city_service_assistant.config import config


def setup_logger(name, log_file=None):
    if log_file is None:
        log_file = config.LOG_FILE

    # 创建日志文件夹
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # 获取日志记录器
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    # 防止重复输出的关键！
    logger.propagate = False

    # 定义日志格式
    formatter = logging.Formatter('%(name)s - %(asctime)s - %(levelname)s - %(message)s')

    # 控制台处理器（仅当尚未添加时）
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)

        # 文件处理器
        file_handler = logging.FileHandler(filename=log_file, encoding="utf-8", mode="a")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)

        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger


# 全局默认 logger
logger = setup_logger("CityServiceAssistant")


if __name__ == "__main__":
    logger.info("日志模块测试：配置输出路径 = %s", config.LOG_FILE)
