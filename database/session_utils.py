"""🧠 The one shared Ollama embedder.

This module used to also house ``with_session_recovery``, a band-aid that
rolled back the old global Session after another task poisoned it. With
per-task sessions (``database.postgres_connection.db_session``) a failed
write can no longer leak state into anyone else's session, so the recovery
shim is gone: every task simply opens its own session.
"""
from logging import getLogger

from langchain_ollama import OllamaEmbeddings

from hephaestus.settings import settings

__all__ = ["embedder"]

logger = getLogger(__name__)

embedder = OllamaEmbeddings(model=settings.memory.embed_model, num_gpu=settings.memory.num_gpu)
