
import asyncio
import functools
import os
from logging import getLogger
from typing import Dict, List, Optional

from mem0 import AsyncMemory
from mem0.configs.base import MemoryConfig, RerankerConfig, VectorStoreConfig, EmbedderConfig, LlmConfig
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from pathlib import Path

from utils.llm_models import mem0_reasoning

logger = getLogger(__name__)

persistent_path = Path(__file__).parent / "persistent_mem0"
persistent_path.mkdir(parents=True, exist_ok=True)

embeddings = OllamaEmbeddings(model="mxbai-embed-large")

# ✅ Chroma supports in-memory mode and dict-based filters (officially supported by mem0)
vector_store = Chroma(
    collection_name="mem0_memories",
    embedding_function=embeddings,
    persist_directory=persistent_path
)


config = MemoryConfig(
    llm=LlmConfig(
        provider="langchain",
        config={
            "model": mem0_reasoning,
        }
    ),
    vector_store=VectorStoreConfig(
        provider="langchain",
        config={
            "client": vector_store,
        }
    ),
    embedder=EmbedderConfig(
        provider="langchain",
        config={
            "model": embeddings,
        }
    ),
    reranker=RerankerConfig(
        provider="huggingface",
        config={
            "model": "BAAI/bge-reranker-large",
            "device": "cuda",
            "top_n": 15  # 🎯 Set to highest limit needed (for DM)
        }),
)

memory = AsyncMemory(config=config)


def _wrap_chroma_filters(filters: Optional[Dict]) -> Optional[Dict]:
    """Chroma requires exactly one top-level key in `where`.
    mem0 builds flat dicts like {"field": "val", "user_id": "user"} which
    Chroma rejects. Wrap multi-key dicts in $and automatically."""
    if not filters or len(filters) <= 1:
        return filters
    return {"$and": [{k: v} for k, v in filters.items()]}


_original_vs_search = memory.vector_store.search
_original_vs_list = memory.vector_store.list


@functools.wraps(_original_vs_search)
def _patched_vs_search(query: str, vectors: List[List[float]], limit: int = 5, filters: Optional[Dict] = None):
    logger.debug(f"🔍 Chroma search filter patch: {filters}")
    return _original_vs_search(query=query, vectors=vectors, limit=limit, filters=_wrap_chroma_filters(filters))


@functools.wraps(_original_vs_list)
def _patched_vs_list(filters=None, limit=None):
    logger.debug(f"🔍 Chroma list filter patch: {filters}")
    return _original_vs_list(filters=_wrap_chroma_filters(filters), limit=limit)


memory.vector_store.search = _patched_vs_search
memory.vector_store.list = _patched_vs_list

