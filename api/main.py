import logging

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=["*"],
)

app = FastAPI(
    title="Dionysus",
    version="0.1.0",
    debug=True,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


socket_app = socketio.ASGIApp(sio, other_asgi_app=app)


# --- SocketIO events ---


@sio.event
async def connect(sid: str, environ: dict[str, object]) -> None:
    logger.info("🔌 Client connected: %s", sid)


@sio.event
async def disconnect(sid: str) -> None:
    logger.info("🔌 Client disconnected: %s", sid)


@sio.event
async def message(sid: str, data: dict[str, object]) -> None:
    logger.info("💬 Message from %s: %s", sid, data)
    await sio.emit("message", data, to=sid)
