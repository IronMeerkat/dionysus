import logging

from hephaestus.logging import init_logger
init_logger()

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.events import register_events
from api.routes.routes import router
from api.routes.session import session_router
from api.routes.conversations import conversations_router

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
app.include_router(session_router)
app.include_router(conversations_router)
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
