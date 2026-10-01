# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 一键停止脚本

读取 logs/all_processes.json 中记录的 4 个服务 PID，
统一终止（Windows 下用 taskkill /T /F 递归结束子进程树，
保证 A2A 子代理内嵌拉起的 MCP stdio 子进程一并退出）。

用法（在项目根目录 D:\\car 下执行）：
    python -m city_service_assistant.scripts.stop_all
    或 python city_service_assistant/scripts/stop_all.py

若 PID 清单不存在（尚未启动或已停止），脚本仅给出提示并退出。
"""
import json
import os
import subprocess
import sys

# 将项目根目录加入 Python 路径，兼容 -m 与直接运行两种方式
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from city_service_assistant.create_logger import logger  # noqa: E402

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
PID_FILE = os.path.join(PROJECT_ROOT, "logs", "all_processes.json")


def _kill_pid(pid: int) -> bool:
    """按 PID 终止进程（Windows 用 taskkill 递归结束子进程树）"""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            os.kill(pid, 15)  # SIGTERM
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("终止进程 %s 失败: %s", pid, e)
        return False


def stop_all():
    """读取 PID 清单并统一终止全部服务进程"""
    if not os.path.exists(PID_FILE):
        logger.warning("未找到 PID 清单: %s（可能尚未启动或已停止）", PID_FILE)
        print("未找到 PID 清单，可能服务尚未启动或已停止。")
        return

    with open(PID_FILE, "r", encoding="utf-8") as f:
        procs = json.load(f)

    if not procs:
        print("PID 清单为空，无需停止。")
        return

    print("\n" + "=" * 60)
    print("正在停止城市公共服务智能助手全部服务...")
    for p in procs:
        pid = p.get("pid")
        name = p.get("name", str(pid))
        if _kill_pid(pid):
            print(f"  已停止 [{name}] pid={pid}")
            logger.info("已停止 %s (pid=%s)", name, pid)
    print("=" * 60)


if __name__ == "__main__":
    stop_all()
