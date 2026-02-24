import logging

from hephaestus.logging import init_logger
init_logger()

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.events import register_events
from api.routes import router

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

app.include_router(router)
register_events(sio)

socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
