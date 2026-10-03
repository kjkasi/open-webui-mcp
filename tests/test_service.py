from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx
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
        self.start_count = 0
        self.close_count = 0

    async def start(self) -> None:
        self.start_count += 1

    async def close(self) -> None:
        self.close_count += 1

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


class BlockingCloseClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.close_started = asyncio.Event()
        self.allow_close = asyncio.Event()

    async def close(self) -> None:
        self.close_started.set()
        await self.allow_close.wait()
        self.close_count += 1


@pytest.mark.asyncio
async def test_shared_client_closes_only_after_last_lifespan() -> None:
    client = FakeClient()
    service = KnowledgeService(cast(OpenWebUIClient, client), settings())

    await service.start()
    await service.start()
    await service.close()

    assert client.start_count == 1
    assert client.close_count == 0

    await service.close()
    await service.close()
    assert client.close_count == 1


@pytest.mark.asyncio
async def test_final_close_completes_before_propagating_cancellation() -> None:
    client = BlockingCloseClient()
    service = KnowledgeService(cast(OpenWebUIClient, client), settings())

    await service.start()
    close_task = asyncio.create_task(service.close())
    await client.close_started.wait()

    close_task.cancel()
    client.allow_close.set()

    with pytest.raises(asyncio.CancelledError):
        await close_task
    assert client.close_count == 1


@pytest.mark.asyncio
async def test_final_close_completes_before_propagating_repeated_cancellation() -> None:
    client = BlockingCloseClient()
    service = KnowledgeService(cast(OpenWebUIClient, client), settings())

    await service.start()
    close_task = asyncio.create_task(service.close())
    await client.close_started.wait()

    close_task.cancel()
    await asyncio.sleep(0)
    close_task.cancel()
    client.allow_close.set()

    with pytest.raises(asyncio.CancelledError):
        await close_task
    assert client.close_count == 1


@pytest.mark.asyncio
async def test_real_client_lifecycle_closes_http_session() -> None:
    client = OpenWebUIClient(
        "http://webui.test",
        "secret-token",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[])),
    )
    service = KnowledgeService(client, settings())

    await service.start()
    assert client._http is not None

    await service.close()

    assert client._http is None


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
