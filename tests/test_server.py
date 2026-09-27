from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import SecretStr

from open_webui_mcp.client import OpenWebUIClient
from open_webui_mcp.config import Settings
from open_webui_mcp.models import SearchResult
from open_webui_mcp.server import create_mcp
from open_webui_mcp.service import KnowledgeService


class FakeClient:
    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def search_document(self, **_: Any) -> list[SearchResult]:
        return [SearchResult(content="fragment", source="manual.md", score=0.9)]

    async def search_collection(self, **_: Any) -> list[SearchResult]:
        return []

    async def list_knowledge_bases(self) -> list[Any]:
        return []


@pytest.mark.asyncio
async def test_mcp_exposes_tools_and_returns_structured_search() -> None:
    settings = Settings(openwebui_api_key=SecretStr("secret"), openwebui_knowledge_id="kb-1")
    service = KnowledgeService(cast(OpenWebUIClient, FakeClient()), settings)
    mcp = create_mcp(settings, service)

    tools = await mcp.list_tools()
    result, _ = await mcp.call_tool("search_knowledge", {"query": "find this"})

    assert {tool.name for tool in tools} == {"search_knowledge", "list_knowledge_bases"}
    serialized_result = str(result)
    assert "manual.md" in serialized_result
    assert "find this" in serialized_result
