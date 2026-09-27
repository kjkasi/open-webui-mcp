from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import OpenWebUIClient
from .config import Settings
from .models import SearchRequest
from .service import KnowledgeService


def create_service(settings: Settings) -> KnowledgeService:
    client = OpenWebUIClient(
        base_url=settings.openwebui_base_url,
        api_key=settings.openwebui_api_key.get_secret_value(),
        timeout_seconds=settings.openwebui_timeout_seconds,
        max_retries=settings.openwebui_max_retries,
    )
    return KnowledgeService(client, settings)


def create_mcp(settings: Settings, service: KnowledgeService | None = None) -> FastMCP:
    """Build an isolated FastMCP instance, which makes protocol tests straightforward."""

    service = service or create_service(settings)

    @asynccontextmanager
    async def lifespan(_server: FastMCP[Any]) -> AsyncIterator[None]:
        await service.start()
        try:
            yield None
        finally:
            await service.close()

    mcp = FastMCP(
        "Open WebUI Knowledge Search",
        instructions=(
            "Read-only semantic search over Open WebUI knowledge bases. "
            "Search results include document sources and relevance signals."
        ),
        host=settings.mcp_host,
        port=settings.mcp_port,
        streamable_http_path="/mcp",
        lifespan=lifespan,
        log_level=settings.log_level,  # type: ignore[arg-type]
    )

    @mcp.tool(
        name="search_knowledge",
        description=(
            "Search Open WebUI knowledge bases for relevant document fragments. "
            "Returns content, source, file ID, score, and metadata without generated prose."
        ),
    )
    async def search_knowledge(
        query: str,
        knowledge_id: str | None = None,
        knowledge_ids: list[str] | None = None,
        top_k: int = 5,
        hybrid: bool | None = None,
        reranker_k: int | None = None,
        relevance_threshold: float | None = None,
        hybrid_bm25_weight: float | None = None,
        enable_enriched_texts: bool | None = None,
    ) -> dict[str, Any]:
        request = SearchRequest(
            query=query,
            knowledge_id=knowledge_id,
            knowledge_ids=knowledge_ids,
            top_k=top_k,
            hybrid=hybrid,
            reranker_k=reranker_k,
            relevance_threshold=relevance_threshold,
            hybrid_bm25_weight=hybrid_bm25_weight,
            enable_enriched_texts=enable_enriched_texts,
        )
        response = await service.search(request)
        return response.model_dump(mode="json")

    @mcp.tool(
        name="list_knowledge_bases",
        description=(
            "List accessible Open WebUI knowledge bases and safe metadata for selecting one."
        ),
    )
    async def list_knowledge_bases() -> list[dict[str, Any]]:
        bases = await service.list_knowledge_bases()
        return [base.model_dump(mode="json") for base in bases]

    return mcp
