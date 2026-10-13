"""🕳️ Transport-free ``TurnSink`` implementations.

``NullTurnSink`` is what a headless turn narrates into: scripts, evals, and
tests run the graph with no client attached. It exists so nodes can always
``await ctx.sink.stream_token(...)`` unconditionally instead of branching on
whether a socket is present -- the two branches used to compute their results
differently, which made headless runs disagree with live play.

``RecordingTurnSink`` captures the call sequence for assertions.
"""
from logging import getLogger

logger = getLogger(__name__)


class NullTurnSink:
    """🕳️ Discards narration: a turn with no client attached.

    Not an error path -- headless execution is a supported mode -- so this
    stays at debug level rather than warning on every token.
    """

    async def stream_start(self, message_id: str, speaker: str) -> None:
        logger.debug(f"🕳️ [null sink] stream_start {speaker} ({message_id})")

    async def stream_end(self, message_id: str, content: str | None = None) -> None:
        logger.debug(f"🕳️ [null sink] stream_end ({message_id})")

    async def stream_token(self, message_id: str, token: str) -> None:
        return None

    async def error(self, message: str) -> None:
        # An error still matters with no client attached: it is the only trace
        # a headless run leaves of a failed turn.
        logger.error(f"🕳️ [null sink] turn error discarded: {message}")


class RecordingTurnSink:
    """📼 Records every call as a ``(method, *args)`` tuple, for tests.

    ``stream_end`` records ``content`` verbatim, including ``None``, so tests
    can tell "keep what streamed" apart from "retract the bubble".
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def stream_start(self, message_id: str, speaker: str) -> None:
        self.calls.append(("stream_start", message_id, speaker))

    async def stream_end(self, message_id: str, content: str | None = None) -> None:
        self.calls.append(("stream_end", message_id, content))

    async def stream_token(self, message_id: str, token: str) -> None:
        self.calls.append(("stream_token", message_id, token))

    async def error(self, message: str) -> None:
        self.calls.append(("error", message))
