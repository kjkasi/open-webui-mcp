from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import SecretStr, ValidationError

from open_webui_mcp.client import OpenWebUIClient
from open_webui_mcp.config import Settings
from open_webui_mcp.errors import InputValidationError
from open_webui_mcp.models import SearchRequest, SearchResult
from open_webui_mcp.service import KnowledgeService


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def search_document(self, **kwargs: Any) -> list[SearchResult]:
        self.calls.append(("document", kwargs))
        return [SearchResult(content="one", source="one.md")]

    async def search_collection(self, **kwargs: Any) -> list[SearchResult]:
        self.calls.append(("collection", kwargs))
        return [SearchResult(content="many", source="many.md")]

    async def list_knowledge_bases(self) -> list[Any]:
        return []


def settings(**kwargs: Any) -> Settings:
    return Settings(openwebui_api_key=SecretStr("secret"), **kwargs)


@pytest.mark.asyncio
async def test_default_id_and_single_collection_endpoint() -> None:
    client = FakeClient()
    service = KnowledgeService(
        cast(OpenWebUIClient, client), settings(openwebui_knowledge_id="default-kb")
    )

    response = await service.search(SearchRequest(query="hello", top_k=2))

    assert response.knowledge_ids == ["default-kb"]
    assert client.calls[0][0] == "document"
    assert client.calls[0][1]["collection_name"] == "default-kb"


@pytest.mark.asyncio
async def test_multiple_ids_use_collection_endpoint_and_allowlist() -> None:
    client = FakeClient()
    service = KnowledgeService(
        cast(OpenWebUIClient, client),
        settings(openwebui_allowed_knowledge_ids=["kb-a", "kb-b"]),
    )

    await service.search(SearchRequest(query="hello", knowledge_ids=["kb-a", "kb-b"]))

    assert client.calls[0][0] == "collection"
    assert client.calls[0][1]["collection_names"] == ["kb-a", "kb-b"]


@pytest.mark.asyncio
async def test_allowlist_blocks_before_upstream_call() -> None:
    client = FakeClient()
    service = KnowledgeService(
        cast(OpenWebUIClient, client),
        settings(openwebui_allowed_knowledge_ids=["safe-kb"]),
    )

    with pytest.raises(InputValidationError):
        await service.search(SearchRequest(query="hello", knowledge_id="private-kb"))
    assert client.calls == []


def test_search_request_rejects_empty_or_ambiguous_selection() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query=" ")
    with pytest.raises(ValidationError):
        SearchRequest(query="hello", knowledge_id="one", knowledge_ids=["two"])
    with pytest.raises(ValidationError):
        SearchRequest(query="hello", knowledge_ids=[])
