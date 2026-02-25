import logging

from hephaestus.logging import init_logger
init_logger()

import socketio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException
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


@app.middleware("http")
async def log_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        logger.exception(f"💥 Unhandled exception on {request.method} {request.url.path}")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(router)
register_events(sio)
app.include_router(session_router)
app.include_router(conversations_router)
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if 400 <= exc.status_code < 500:
        logger.warning(f"🔥 User (probably) induced error: {exc.status_code}", exc_info=True)
    else:
        logger.error(f"💥 Server error: {exc.status_code}", exc_info=True)

    return JSONResponse(status_code=exc.status_code, content={"detail": '\n'.join(exc.args)})


@app.exception_handler(Exception)
async def exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"💥 Server error: {exc.__class__.__name__}")
    return JSONResponse(status_code=500, content={"detail": '\n'.join(exc.args)})
