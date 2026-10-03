from __future__ import annotations

from typing import Any

import httpx
import pytest

from open_webui_mcp.client import OpenWebUIClient, normalize_retrieval_response
from open_webui_mcp.errors import AuthenticationError, UpstreamProtocolError, UpstreamTimeoutError


@pytest.mark.asyncio
async def test_single_search_sends_bearer_and_upstream_payload() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["authorization"]
        seen["path"] = request.url.path
        seen["json"] = request.read()
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "content": "Relevant text",
                        "source": "guide.pdf",
                        "file_id": "file-1",
                        "score": 0.82,
                        "metadata": {"page": 3},
                    }
                ]
            },
        )

    client = OpenWebUIClient(
        "http://webui.test",
        "secret-token",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    results = await client.search_document(
        collection_name="kb-1",
        query="how does auth work",
        top_k=3,
        reranker_k=10,
        relevance_threshold=0.4,
        hybrid=True,
        hybrid_bm25_weight=0.2,
    )
    await client.close()

    assert seen["authorization"] == "Bearer secret-token"
    assert seen["path"] == "/api/v1/retrieval/query/doc"
    assert b'"collection_name":"kb-1"' in seen["json"]  # type: ignore[operator]
    assert b'"k":3' in seen["json"]  # type: ignore[operator]
    assert results[0].source == "guide.pdf"
    assert results[0].score == 0.82


@pytest.mark.asyncio
async def test_list_knowledge_bases_follows_all_pages() -> None:
    requested_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        requested_pages.append(page)
        if page == "1":
            return httpx.Response(
                200,
                json={
                    "items": [{"id": "kb-1", "name": "First"}],
                    "total": 2,
                },
            )
        return httpx.Response(
            200,
            json={"items": [{"id": "kb-2", "name": "Second"}], "total": 2},
        )

    client = OpenWebUIClient(
        "http://webui.test", "secret-token", max_retries=0, transport=httpx.MockTransport(handler)
    )
    bases = await client.list_knowledge_bases()
    await client.close()

    assert requested_pages == ["1", "2"]
    assert [base.id for base in bases] == ["kb-1", "kb-2"]


@pytest.mark.asyncio
async def test_list_knowledge_bases_rejects_repeated_nonempty_pages() -> None:
    requested_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_pages.append(request.url.params["page"])
        if len(requested_pages) > 2:
            raise AssertionError("pagination did not detect repeated page data")
        return httpx.Response(
            200,
            json={"items": [{"id": "kb-1", "name": "First"}], "total": 3},
        )

    client = OpenWebUIClient(
        "http://webui.test", "secret-token", max_retries=0, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(UpstreamProtocolError):
        await client.list_knowledge_bases()
    await client.close()

    assert requested_pages == ["1", "2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("total", ["2", True])
async def test_list_knowledge_bases_rejects_invalid_totals(total: Any) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"items": [{"id": "kb-1", "name": "First"}], "total": total},
        )

    client = OpenWebUIClient(
        "http://webui.test", "secret-token", max_retries=0, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(UpstreamProtocolError):
        await client.list_knowledge_bases()
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [0, -1, "1"])
async def test_list_knowledge_bases_rejects_invalid_start_page(page: Any) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid page reached upstream")

    client = OpenWebUIClient(
        "http://webui.test", "secret-token", max_retries=0, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ValueError, match="page must be an integer >= 1"):
        await client.list_knowledge_bases(page=page)
    await client.close()


@pytest.mark.asyncio
async def test_close_clears_http_client_when_close_fails() -> None:
    class FailingHttpClient:
        async def aclose(self) -> None:
            raise RuntimeError("close failed")

    client = OpenWebUIClient("http://webui.test", "secret-token")
    client._http = FailingHttpClient()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="close failed"):
        await client.close()

    assert client._http is None


def test_normalize_chroma_shape() -> None:
    results = normalize_retrieval_response(
        {
            "documents": [["first fragment", "second fragment"]],
            "metadatas": [[{"source": "one.md", "file_id": "a"}, {"source": "two.md"}]],
            "distances": [[0.1, 0.4]],
        }
    )

    assert [item.content for item in results] == ["first fragment", "second fragment"]
    assert results[0].source == "one.md"
    assert results[0].file_id == "a"
    assert results[1].score == 0.4


@pytest.mark.asyncio
async def test_authentication_error_does_not_expose_key() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "secret-token is invalid"})

    client = OpenWebUIClient(
        "http://webui.test", "secret-token", max_retries=0, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(AuthenticationError) as raised:
        await client.list_knowledge_bases()
    await client.close()

    assert "secret-token" not in str(raised.value)


@pytest.mark.asyncio
async def test_timeout_is_mapped_without_retrying_forever() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("upstream timeout")

    client = OpenWebUIClient(
        "http://webui.test", "secret-token", max_retries=0, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(UpstreamTimeoutError):
        await client.list_knowledge_bases()
    await client.close()
