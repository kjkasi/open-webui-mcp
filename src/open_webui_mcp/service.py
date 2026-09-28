from __future__ import annotations

import asyncio

from .client import OpenWebUIClient
from .config import Settings
from .errors import ConfigurationError, InputValidationError
from .models import KnowledgeBaseSummary, SearchRequest, SearchResponse


class KnowledgeService:
    """Applies local selection policy before delegating to Open WebUI."""

    def __init__(self, client: OpenWebUIClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self._lifecycle_lock = asyncio.Lock()
        self._active_lifespans = 0

    async def start(self) -> None:
        """Acquire one FastMCP session's shared client lease."""
        async with self._lifecycle_lock:
            if self._active_lifespans == 0:
                await self.client.start()
            self._active_lifespans += 1

    async def close(self) -> None:
        """Release one session lease, closing the client after the last session."""
        async with self._lifecycle_lock:
            if self._active_lifespans == 0:
                return
            self._active_lifespans -= 1
            if self._active_lifespans == 0:
                await self.client.close()

    async def search(self, request: SearchRequest) -> SearchResponse:
        knowledge_ids = self.resolve_knowledge_ids(request)
        if len(knowledge_ids) == 1:
            results = await self.client.search_document(
                collection_name=knowledge_ids[0],
                query=request.query,
                top_k=request.top_k,
                reranker_k=request.reranker_k,
                relevance_threshold=request.relevance_threshold,
                hybrid=request.hybrid,
                hybrid_bm25_weight=request.hybrid_bm25_weight,
            )
        else:
            results = await self.client.search_collection(
                collection_names=knowledge_ids,
                query=request.query,
                top_k=request.top_k,
                reranker_k=request.reranker_k,
                relevance_threshold=request.relevance_threshold,
                hybrid=request.hybrid,
                hybrid_bm25_weight=request.hybrid_bm25_weight,
                enable_enriched_texts=request.enable_enriched_texts,
            )
        return SearchResponse(
            query=request.query, knowledge_ids=knowledge_ids, results=results, count=0
        )

    async def list_knowledge_bases(self) -> list[KnowledgeBaseSummary]:
        bases = await self.client.list_knowledge_bases()
        allowlist = self._allowlist
        if allowlist is None:
            return bases
        return [base for base in bases if base.id in allowlist]

    def resolve_knowledge_ids(self, request: SearchRequest) -> list[str]:
        if request.knowledge_id:
            selected = [request.knowledge_id]
        elif request.knowledge_ids is not None:
            if not request.knowledge_ids:
                raise InputValidationError("knowledge_ids must not be empty")
            selected = request.knowledge_ids
        elif self.settings.openwebui_knowledge_id:
            selected = [self.settings.openwebui_knowledge_id]
        else:
            raise ConfigurationError(
                "No knowledge base selected; set knowledge_id or OPENWEBUI_KNOWLEDGE_ID"
            )

        allowlist = self._allowlist
        if allowlist is not None:
            forbidden = [item for item in selected if item not in allowlist]
            if forbidden:
                raise InputValidationError("Requested knowledge base is not allowed")
        return selected

    @property
    def _allowlist(self) -> set[str] | None:
        values = self.settings.openwebui_allowed_knowledge_ids
        return set(values) if values else None
