import os
from collections.abc import Iterable
from logging import getLogger

from langchain_ollama import OllamaEmbeddings

from graphiti_core import Graphiti
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from hephaestus.settings import settings

logger = getLogger(__name__)

XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
XAI_BASE_URL = "https://api.x.ai/v1"
XAI_MODEL = "grok-4-1-fast-non-reasoning"
XAI_SMALL_MODEL = "grok-4-1-fast-non-reasoning"

OLLAMA_EMBED_MODEL = "mxbai-embed-large"
OLLAMA_EMBED_DIM = 1024
OLLAMA_NUM_GPU = 99


class OllamaEmbedder(EmbedderClient):
    """Graphiti embedder backed by Ollama's native API (GPU-accelerated)."""

    def __init__(self, model: str = OLLAMA_EMBED_MODEL, num_gpu: int = OLLAMA_NUM_GPU):
        self.config = EmbedderConfig(embedding_dim=OLLAMA_EMBED_DIM)
        self._client = OllamaEmbeddings(model=model, num_gpu=num_gpu)

    async def create(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> list[float]:
        if isinstance(input_data, str):
            return await self._client.aembed_query(input_data)
        if isinstance(input_data, list) and input_data and isinstance(input_data[0], str):
            results = await self._client.aembed_documents(input_data)
            return results[0]
        return await self._client.aembed_query(str(input_data))

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        return await self._client.aembed_documents(input_data_list)


llm_config = LLMConfig(
    api_key=XAI_API_KEY,
    base_url=XAI_BASE_URL,
    model=XAI_MODEL,
    small_model=XAI_SMALL_MODEL,
)

llm_client = OpenAIGenericClient(config=llm_config)

embedder = OllamaEmbedder()

cross_encoder = OpenAIRerankerClient(
    config=LLMConfig(
        api_key=XAI_API_KEY,
        base_url=XAI_BASE_URL,
        model=XAI_SMALL_MODEL,
    )
)

graphiti = Graphiti(
    uri=settings.NEO4J.NEO4J_URI,
    user=settings.NEO4J.NEO4J_USER,
    password=settings.NEO4J.NEO4J_PASSWORD,
    llm_client=llm_client,
    embedder=embedder,
    cross_encoder=cross_encoder,
)


async def initialize_graphiti():
    """Build Neo4j indices and constraints. Call once at application startup."""
    logger.info("🏗️ Initializing Graphiti indices and constraints...")
    await graphiti.build_indices_and_constraints()
    logger.info("✅ Graphiti initialization complete")


async def shutdown_graphiti():
    """Close the Neo4j driver. Call at application shutdown."""
    logger.info("🔌 Closing Graphiti connection...")
    await graphiti.close()
    logger.info("✅ Graphiti connection closed")
