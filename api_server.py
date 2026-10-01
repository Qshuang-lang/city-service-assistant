# -*- coding: utf-8 -*-
"""
城市公共服务智能助手 - A2A 总代理服务（FastAPI）

同构复刻 SmartVoyage 参考项目 api_server.py，端口取 config.API_SERVER_PORT（默认 8080）。

接口：
    POST /api/chat          标准对话（意图识别 → 路由 → 回复）
    POST /api/chat/stream   SSE 流式对话
    GET  /api/memory        记忆状态
    POST /api/memory/profile 更新用户画像
    POST /api/memory/clear  清空记忆
    GET  /api/agents        三个 A2A 子代理卡片信息

启动：
    python -m city_service_assistant.api_server
"""
import json
import os

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from city_service_assistant.chat_service import ChatService
from city_service_assistant.config import config
from city_service_assistant.create_logger import logger

app = FastAPI(
    title="City Service Assistant API",
    description="基于 A2A 的城市公共服务智能助手（气象环境/交通出行/生活政务）",
)

# 全局总代理服务实例（启动时从 MySQL 加载持久化记忆）
chat_service = ChatService()


class ChatRequest(BaseModel):
    message: str


class ProfileRequest(BaseModel):
    profile: dict


@app.get("/")
async def index():
    """健康检查 / 服务说明"""
    return {
        "service": "city-service-assistant",
        "status": "ok",
        "endpoints": ["/api/chat", "/api/chat/stream", "/api/memory",
                      "/api/memory/profile", "/api/memory/clear", "/api/agents"],
    }


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """发送消息，获取非流式回复"""
    response = await chat_service.chat(request.message)
    return {"status": "success", "message": response}


async def sse_generator(message: str):
    """SSE 生成器：逐 chunk 流式返回回复"""
    async for chunk in chat_service.chat_stream(message):
        yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """发送消息，SSE 流式获取回复"""
    return StreamingResponse(sse_generator(request.message), media_type="text/event-stream")


@app.get("/api/memory")
async def get_memory():
    """获取记忆状态"""
    return {"status": "success", "data": chat_service.get_memory_state()}


@app.post("/api/memory/profile")
async def update_profile(request: ProfileRequest):
    """更新用户画像"""
    chat_service.update_user_profile(request.profile)
    return {"status": "success", "message": "用户画像已更新"}


@app.post("/api/memory/clear")
async def clear_memory():
    """清空记忆"""
    chat_service.clear_memory()
    return {"status": "success", "message": "记忆已清空"}


@app.get("/api/agents")
async def get_agents():
    """获取三个 A2A 子代理卡片信息"""
    return {"status": "success", "data": chat_service.get_agent_cards()}


# 同源托管前端页面（static/index.html），前端通过相对路径 /api/* 调用本服务
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    logger.info("启动 A2A 总代理服务: 127.0.0.1:%s", config.API_SERVER_PORT)
    uvicorn.run(app, host="127.0.0.1", port=config.API_SERVER_PORT, log_level="info")
