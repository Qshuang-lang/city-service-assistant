# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - 一键启动脚本

启动 3 个 A2A 子代理（weather 5005 / traffic 5006 / life 5007）
与总代理 api_server（config.API_SERVER_PORT，默认 8080），共 4 个进程。

用法（在项目根目录 D:\\car 下执行）：
    python -m city_service_assistant.scripts.start_all
    或 python city_service_assistant/scripts/start_all.py

统一退出：前台运行中按 Ctrl+C，或另开终端执行 stop_all.py。
各进程 stdout/stderr 追加写入 logs/start_all_*.log；
PID 清单写入 logs/all_processes.json，供 stop_all.py 统一终止。

注：MCP 层由 A2A 子代理以 stdio 子进程自动拉起，无需在此启动。
若 8080 被占用（如 Milvus Attu），可用环境变量覆盖端口：
    set API_SERVER_PORT=8090
"""
import json
import os
import subprocess
import sys
import time

# 将项目根目录加入 Python 路径，兼容 -m 与直接运行两种方式
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from city_service_assistant.config import config  # noqa: E402
from city_service_assistant.create_logger import logger  # noqa: E402

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
PID_FILE = os.path.join(LOGS_DIR, "all_processes.json")

# 待启动进程清单：(展示名, 模块名)
PROCESSES = [
    ("weather(5005)", "city_service_assistant.a2a_server.weather_server"),
    ("traffic(5006)", "city_service_assistant.a2a_server.traffic_server"),
    ("life(5007)", "city_service_assistant.a2a_server.life_server"),
    (f"api_server({config.API_SERVER_PORT})", "city_service_assistant.api_server"),
]


def _log_path(name: str) -> str:
    """按进程名生成日志文件路径（去除括号等非法字符）"""
    safe = name.replace("(", "_").replace(")", "").replace(":", "")
    return os.path.join(LOGS_DIR, f"start_all_{safe}.log")


def _terminate(procs: list):
    """终止已启动的子进程（Windows 下用 taskkill 递归结束子进程树）"""
    for p in procs:
        proc = p["proc"]
        if proc.poll() is not None:
            continue
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, timeout=10)
            else:
                proc.terminate()
            logger.info("已停止 %s (pid=%s)", p["name"], proc.pid)
        except Exception as e:  # noqa: BLE001
            logger.warning("停止 %s 失败: %s", p["name"], e)


def start_all():
    """启动全部服务并前台驻留，等待 Ctrl+C 统一退出"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    procs = []

    for name, module in PROCESSES:
        log_file = open(_log_path(name), "a", encoding="utf-8")
        # Windows 下隐藏子进程控制台窗口，统一由本进程托管
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(
            [sys.executable, "-m", module],
            cwd=PROJECT_ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        procs.append({"name": name, "module": module, "pid": proc.pid, "proc": proc})
        logger.info("已启动 %s (pid=%s), 日志: %s", name, proc.pid, _log_path(name))

    # 持久化 PID 清单（供 stop_all.py 统一终止）
    with open(PID_FILE, "w", encoding="utf-8") as f:
        json.dump(
            [{"name": p["name"], "module": p["module"], "pid": p["pid"]} for p in procs],
            f, ensure_ascii=False, indent=2,
        )
    logger.info("PID 清单已写入: %s", PID_FILE)

    print("\n" + "=" * 60)
    print("城市公共服务智能助手 - 全部服务已启动")
    for p in procs:
        print(f"  [{p['name']}] pid={p['pid']}")
    print(f"  总代理地址: http://127.0.0.1:{config.API_SERVER_PORT}")
    print("  按 Ctrl+C 统一退出所有服务；另开终端可执行 stop_all.py")
    print("=" * 60)

    try:
        while True:
            # 监控子进程是否异常退出，仅提示不自动重启
            for p in list(procs):
                proc = p["proc"]
                if proc.poll() is not None:
                    logger.warning("进程 %s (pid=%s) 已退出，退出码=%s",
                                   p["name"], proc.pid, proc.returncode)
                    procs.remove(p)
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n收到退出信号，正在统一停止全部服务...")
        _terminate(procs)
        print("全部服务已停止。")
        sys.exit(0)


if __name__ == "__main__":
    start_all()
