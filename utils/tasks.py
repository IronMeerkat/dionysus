"""Fire-and-forget background task scheduling with error logging."""
import asyncio
import contextvars
from logging import getLogger

logger = getLogger(__name__)


def _log_background_task_exception(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("🔥 Background task failed", exc_info=exc)


def fire_and_forget(coro: object) -> asyncio.Task[None]:
    """Schedule a coroutine as a background task with automatic error logging.

    Uses a blank ``contextvars.Context`` so LangChain/LangGraph streaming
    callbacks from the calling graph node are NOT inherited by the task.
    """
    task = asyncio.create_task(coro, context=contextvars.Context())
    task.add_done_callback(_log_background_task_exception)
    return task
