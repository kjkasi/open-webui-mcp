from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .errors import (
    AccessDeniedError,
    AuthenticationError,
    RateLimitError,
    ResourceNotFoundError,
    UpstreamProtocolError,
    UpstreamServiceError,
    UpstreamTimeoutError,
    UpstreamValidationError,
)
from .models import KnowledgeBaseSummary, SearchResult

logger = logging.getLogger(__name__)


class OpenWebUIClient:
    """Small API adapter; Open WebUI remains the authority for ACL decisions."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=httpx.Timeout(self.timeout_seconds),
                transport=self._transport,
            )

    async def close(self) -> None:
        if self._http is None:
            return
        try:
            await self._http.aclose()
        finally:
            self._http = None

    async def __aenter__(self) -> OpenWebUIClient:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def list_knowledge_bases(self, page: int = 1) -> list[KnowledgeBaseSummary]:
        """Return all accessible knowledge bases, following upstream pagination."""
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("page must be an integer >= 1")

        all_items: list[KnowledgeBaseSummary] = []
        current_page = page
        total: int | None = None
        seen_ids: set[str] = set()

        while True:
            payload = await self._request_json(
                "GET", "/api/v1/knowledge/", params={"page": current_page}
            )
            items, page_total = self._knowledge_base_page(payload)
            if page_total is not None:
                if total is None:
                    total = page_total
                elif page_total != total:
                    raise UpstreamProtocolError(
                        "Open WebUI returned inconsistent knowledge base totals"
                    )
            if items:
                page_ids = [item.id for item in items]
                if len(set(page_ids)) != len(page_ids):
                    raise UpstreamProtocolError(
                        "Open WebUI returned duplicate knowledge base IDs"
                    )
                if seen_ids.intersection(page_ids):
                    raise UpstreamProtocolError(
                        "Open WebUI returned overlapping knowledge base pages"
                    )
                seen_ids.update(page_ids)
            all_items.extend(items)

            if total is not None and len(all_items) > total:
                raise UpstreamProtocolError(
                    "Open WebUI returned more knowledge bases than declared"
                )
            if not items:
                if total is not None and len(all_items) < total:
                    raise UpstreamProtocolError(
                        "Open WebUI returned fewer knowledge bases than declared"
                    )
                return all_items
            if total is None or len(all_items) < total:
                current_page += 1
                continue
            return all_items

    @classmethod
    def _knowledge_base_page(
        cls, payload: Any
    ) -> tuple[list[KnowledgeBaseSummary], int | None]:
        if isinstance(payload, dict):
            if "items" not in payload:
                raise UpstreamProtocolError(
                    "Open WebUI returned a knowledge base page without items"
                )
            raw_items = payload["items"]
            if "total" in payload:
                raw_total = payload["total"]
                if isinstance(raw_total, bool) or not isinstance(raw_total, int) or raw_total < 0:
                    raise UpstreamProtocolError(
                        "Open WebUI returned an invalid knowledge base total"
                    )
                total: int | None = raw_total
            else:
                total = None
        else:
            raw_items = payload
            total = None
        if not isinstance(raw_items, list):
            raise UpstreamProtocolError("Open WebUI returned an invalid knowledge base list")
        if any(not isinstance(item, dict) for item in raw_items):
            raise UpstreamProtocolError("Open WebUI returned an invalid knowledge base item")
        return [cls._knowledge_base(item) for item in raw_items], total

    async def search_document(
        self,
        *,
        collection_name: str,
        query: str,
        top_k: int,
        reranker_k: int | None = None,
        relevance_threshold: float | None = None,
        hybrid: bool | None = None,
        hybrid_bm25_weight: float | None = None,
    ) -> list[SearchResult]:
        payload = self._search_payload(
            query=query,
            top_k=top_k,
            reranker_k=reranker_k,
            relevance_threshold=relevance_threshold,
            hybrid=hybrid,
            hybrid_bm25_weight=hybrid_bm25_weight,
        )
        payload["collection_name"] = collection_name
        response = await self._request_json("POST", "/api/v1/retrieval/query/doc", json=payload)
        return normalize_retrieval_response(response)

    async def search_collection(
        self,
        *,
        collection_names: list[str],
        query: str,
        top_k: int,
        reranker_k: int | None = None,
        relevance_threshold: float | None = None,
        hybrid: bool | None = None,
        hybrid_bm25_weight: float | None = None,
        enable_enriched_texts: bool | None = None,
    ) -> list[SearchResult]:
        payload = self._search_payload(
            query=query,
            top_k=top_k,
            reranker_k=reranker_k,
            relevance_threshold=relevance_threshold,
            hybrid=hybrid,
            hybrid_bm25_weight=hybrid_bm25_weight,
        )
        payload["collection_names"] = collection_names
        if enable_enriched_texts is not None:
            payload["enable_enriched_texts"] = enable_enriched_texts
        response = await self._request_json(
            "POST", "/api/v1/retrieval/query/collection", json=payload
        )
        return normalize_retrieval_response(response)

    @staticmethod
    def _search_payload(
        *,
        query: str,
        top_k: int,
        reranker_k: int | None,
        relevance_threshold: float | None,
        hybrid: bool | None,
        hybrid_bm25_weight: float | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query, "k": top_k}
        optional = {
            "k_reranker": reranker_k,
            "r": relevance_threshold,
            "hybrid": hybrid,
            "hybrid_bm25_weight": hybrid_bm25_weight,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})
        return payload

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        await self.start()
        assert self._http is not None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._http.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt < self.max_retries:
                    await self._backoff(attempt)
                    continue
                raise UpstreamTimeoutError("Open WebUI request timed out") from exc

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.max_retries:
                    await self._backoff(attempt)
                    continue
            self._raise_for_status(response)
            try:
                return response.json()
            except ValueError as exc:
                raise UpstreamProtocolError("Open WebUI returned invalid JSON") from exc
        raise UpstreamServiceError("Open WebUI is temporarily unavailable")

    async def _backoff(self, attempt: int) -> None:
        await asyncio.sleep(min(0.25 * (2**attempt), 2.0))

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status == 401:
            raise AuthenticationError("Open WebUI authentication failed")
        if status == 403:
            raise AccessDeniedError("Open WebUI denied access to this resource")
        if status == 404:
            raise ResourceNotFoundError("Open WebUI resource or endpoint was not found")
        if status == 422:
            raise UpstreamValidationError("Open WebUI rejected the request parameters")
        if status == 429:
            raise RateLimitError("Open WebUI rate limit exceeded")
        if status >= 500:
            raise UpstreamServiceError("Open WebUI is temporarily unavailable")
        if status >= 400:
            raise UpstreamServiceError(f"Open WebUI returned HTTP {status}")

    @staticmethod
    def _knowledge_base(item: dict[str, Any]) -> KnowledgeBaseSummary:
        raw_id = item.get("id", item.get("knowledge_id"))
        return KnowledgeBaseSummary(
            id=str(raw_id or ""),
            name=str(item.get("name", "")),
            description=item.get("description"),
            file_count=_file_count(item),
        )


def _file_count(item: dict[str, Any]) -> int | None:
    value = item.get("file_count", item.get("fileCount"))
    if value is None and isinstance(item.get("files"), list):
        return len(item["files"])
    return value if isinstance(value, int) else None


def normalize_retrieval_response(payload: Any) -> list[SearchResult]:
    """Normalize Open WebUI's flat and Chroma-like retrieval response shapes."""

    if isinstance(payload, list):
        return [_result_from_item(item) for item in payload if isinstance(item, (dict, str))]
    if not isinstance(payload, dict):
        raise UpstreamProtocolError("Open WebUI returned an invalid retrieval response")

    raw_results = payload.get("results")
    if isinstance(raw_results, list):
        return [_result_from_item(item) for item in raw_results if isinstance(item, (dict, str))]

    documents = payload.get("documents", [])
    metadatas = payload.get("metadatas", [])
    distances = payload.get("distances", [])
    return _results_from_parallel_arrays(documents, metadatas, distances)


def _results_from_parallel_arrays(
    documents: Any, metadatas: Any, distances: Any
) -> list[SearchResult]:
    docs = _flatten_one_level(documents)
    metadata = _flatten_one_level(metadatas)
    scores = _flatten_one_level(distances)
    results: list[SearchResult] = []
    for index, document in enumerate(docs):
        if not isinstance(document, str):
            continue
        item: dict[str, Any] = {"content": document}
        if index < len(metadata) and isinstance(metadata[index], dict):
            item["metadata"] = metadata[index]
        if index < len(scores) and isinstance(scores[index], (int, float)):
            # The API calls this field distance; preserve its numeric signal as score.
            item["score"] = scores[index]
        results.append(_result_from_item(item))
    return results


def _flatten_one_level(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    if value and all(isinstance(item, list) for item in value):
        return [nested for item in value for nested in item]
    return value


def _result_from_item(item: dict[str, Any] | str) -> SearchResult:
    if isinstance(item, str):
        return SearchResult(content=item)
    raw_metadata = item.get("metadata")
    if not isinstance(raw_metadata, dict):
        raw_metadata = item.get("meta")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    content = item.get("content", item.get("document", item.get("text", "")))
    source = item.get("source") or _first(metadata, "source", "file_name", "filename", "name")
    file_id = item.get("file_id") or _first(metadata, "file_id", "fileId")
    score = item.get("score", item.get("relevance_score", item.get("distance")))
    return SearchResult(
        content=str(content or ""),
        source=str(source) if source is not None else None,
        file_id=str(file_id) if file_id is not None else None,
        score=float(score) if isinstance(score, (int, float)) else None,
        metadata=metadata,
    )


def _first(values: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if values.get(key) is not None:
            return values[key]
    return None
