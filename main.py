# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - CLI 客户端（main.py）

用法：
    python -m city_service_assistant.main

命令：
    直接输入问题 → 调用总代理 chat 返回回复
    clear        → 清空全部记忆
    exit / quit / q → 退出

说明：
    每次 chat 通过 asyncio.run 创建独立事件循环，调用总代理的 A2A 子代理（httpx 异步）。
"""
import asyncio

from city_service_assistant.chat_service import ChatService
from city_service_assistant.create_logger import logger


def main():
    logger.info("启动城市公共服务智能助手 CLI")
    service = ChatService()
    print("城市公共服务智能助手已就绪（输入问题开始，输入 exit 退出，输入 clear 清空记忆）")
    print("-" * 50)

    while True:
        try:
            user_input = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            print("再见")
            break
        if user_input.lower() in ("clear", "重置"):
            service.clear_memory()
            print("助手 > 已清空全部记忆")
            continue

        try:
            response = asyncio.run(service.chat(user_input))
        except Exception as e:  # noqa: BLE001
            logger.error("CLI 调用异常: %s", e)
            response = f"处理失败：{e}"

        print(f"助手 > {response}")
        print("-" * 50)


if __name__ == "__main__":
    main()
