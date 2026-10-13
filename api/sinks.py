"""🔌 The Socket.IO implementation of ``TurnSink``.

This is the only module where the turn vocabulary and Socket.IO meet. Keeping
the engine on the ``TurnSink`` protocol means the transport can be swapped for
a message bus later without touching a single graph node.
"""
from logging import getLogger

import socketio

logger = getLogger(__name__)


class SocketTurnSink:
    """🔌 Emits a turn's narration to one Socket.IO client."""

    def __init__(self, sio: socketio.AsyncServer, sid: str, namespace: str | None = None) -> None:
        self._sio = sio
        self._sid = sid
        self._ns = namespace

    async def stream_start(self, message_id: str, speaker: str) -> None:
        await self._sio.emit(
            "stream_start",
            {"messageId": message_id, "name": speaker},
            to=self._sid,
            namespace=self._ns,
        )

    async def stream_end(self, message_id: str, content: str | None = None) -> None:
        # ``content`` is tri-state (see contracts.turn_events): the key must be
        # ABSENT for "keep what streamed", and present-and-empty to retract the
        # bubble. Normalising None to "" here would delete messages client-side.
        payload: dict[str, str] = {"messageId": message_id}
        if content is not None:
            payload["content"] = content
        await self._sio.emit("stream_end", payload, to=self._sid, namespace=self._ns)

    async def stream_token(self, message_id: str, token: str) -> None:
        await self._sio.emit(
            "stream_token",
            {"messageId": message_id, "token": token},
            to=self._sid,
            namespace=self._ns,
        )

    async def error(self, message: str) -> None:
        await self._sio.emit("error", {"message": message}, to=self._sid, namespace=self._ns)
