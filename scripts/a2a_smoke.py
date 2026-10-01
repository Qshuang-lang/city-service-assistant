# -*- coding: utf-8 -*-
"""
A2A 子代理端到端冒烟测试脚本（官方 a2a-sdk v1 协议）

用法：
    python -m city_service_assistant.scripts.a2a_smoke [模块] [端口] [问题] [标签]

    模块可选：weather(5005) / traffic(5006) / life(5007)
    默认：weather 5005 '北京今天天气怎么样？' weather

流程：
    1. 以子进程启动对应 a2a_server 模块（stdio 模式）
    2. 轮询 /.well-known/agent-card.json 等待就绪
    3. 用官方 A2AClient 通过 HTTP 发送 SendMessage（兼容 proto + JSON 双协议）
    4. 流式读取响应与任务 artifact，输出到 logs/a2a_smoke_<tag>.txt
    5. 结束后回收子进程并附上服务端日志尾部

说明：
    - 输出目录固定为项目 logs/，避免污染临时目录
    - 使用 httpx 长超时 ClientConfig，规避大模型生成耗时导致的客户端超时
"""
import sys, os, json, time, subprocess, traceback

# 项目根目录（本文件位于 city_service_assistant/scripts/ 下）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from city_service_assistant.config import config

# 默认端口映射（与 config.py 保持一致）
DEFAULT_PORTS = {
    "weather": config.A2A_WEATHER_PORT,
    "traffic": config.A2A_TRAFFIC_PORT,
    "life": config.A2A_LIFE_PORT,
}

MODULE = sys.argv[1] if len(sys.argv) > 1 else 'weather'
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORTS[MODULE]
QUESTION = sys.argv[3] if len(sys.argv) > 3 else '北京今天天气怎么样？'
TAG = sys.argv[4] if len(sys.argv) > 4 else MODULE

OUT_DIR = os.path.join(ROOT, 'logs')
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, 'a2a_smoke_%s.txt' % TAG)
SRVLOG = os.path.join(OUT_DIR, 'a2a_smoke_srv_%s.log' % TAG)


def log(msg):
    with open(OUT, 'a', encoding='utf-8') as f:
        f.write(str(msg) + '\n')


procs = []


def start_a2a():
    logf = open(SRVLOG, 'a', encoding='utf-8', errors='replace')
    p = subprocess.Popen(
        [sys.executable, '-m', 'city_service_assistant.a2a_server.' + MODULE + '_server'],
        cwd=ROOT,
        stdout=logf, stderr=subprocess.STDOUT,
    )
    procs.append((p, logf))
    return p


def wait_ready(timeout=60):
    import urllib.request
    url = 'http://127.0.0.1:%d/.well-known/agent-card.json' % PORT
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                json.loads(r.read().decode('utf-8'))
                log('AgentCard 就绪')
                return True
        except Exception:
            time.sleep(1)
    return False


async def main():
    log('== [3] 启动 A2A 服务(%s : %s) ==' % (MODULE, PORT))
    p = start_a2a()
    ok = wait_ready()
    log('服务就绪: %s' % ok)
    if not ok:
        return

    log('== [4] 官方 A2AClient: %s ==' % QUESTION)
    from a2a.client import create_client, ClientConfig
    from a2a.types.a2a_pb2 import Message as PbMsg, SendMessageRequest as PbReq
    import httpx

    # 绕过系统代理直连本地 A2A 服务（与采集/调度策略一致，避免代理转发 127.0.0.1 导致 502）
    h = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0), trust_env=False)
    cfg = ClientConfig(httpx_client=h)
    async with await create_client('http://127.0.0.1:%d/' % PORT, client_config=cfg) as client:
        msg = PbMsg(
            message_id="msg-%s-001" % TAG,
            role=1,  # ROLE_USER
            parts=[{"text": QUESTION}],
        )
        req = PbReq(message=msg)
        log('发送 SendMessage ...')
        t0 = time.time()
        async for resp in client.send_message(req):
            log('[%.1fs] StreamResponse: %s' % (time.time() - t0, str(resp)[:600]))
            task = getattr(resp, 'task', None)
            if task is None and hasattr(resp, 'result'):
                task = resp.result
            if task is not None:
                log('  任务ID: %s  状态: %s' % (
                    getattr(task, 'id', None),
                    getattr(getattr(task, 'status', None), 'state', None)))
                for a in (getattr(task, 'artifacts', None) or []):
                    for part in (a.parts or []):
                        log('  artifacts: %s' % (part.text or '')[:2000])
        log('完成，耗时 %.1fs' % (time.time() - t0))


if __name__ == '__main__':
    import asyncio
    try:
        asyncio.run(main())
        log('')
        log('E2E DONE')
    except Exception:
        log(traceback.format_exc())
    finally:
        for p, f in procs:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(1)
        try:
            with open(SRVLOG, 'r', encoding='utf-8', errors='replace') as f:
                log('')
                log('===== 服务端日志末尾 =====')
                log(f.read()[-4000:])
        except Exception as e:
            log('读日志失败: %s' % e)
