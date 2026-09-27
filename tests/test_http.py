from __future__ import annotations

from pydantic import SecretStr
from starlette.testclient import TestClient

from open_webui_mcp.config import Settings
from open_webui_mcp.http_server import create_http_app


def test_http_health_and_optional_mcp_auth() -> None:
    settings = Settings(
        openwebui_api_key=SecretStr("open-webui-secret"),
        mcp_auth_token=SecretStr("mcp-secret"),
    )
    with TestClient(create_http_app(settings)) as client:
        assert client.get("/health").json() == {"status": True, "ready": False}
        assert client.get("/mcp").status_code == 401
        assert client.get("/mcp", headers={"Authorization": "Bearer mcp-secret"}).status_code == 406
