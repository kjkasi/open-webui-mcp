# open-webui-mcp

Read-only MCP server for semantic search in Open WebUI knowledge bases. The server uses the Open WebUI API, so Open WebUI remains responsible for authentication and access control; it never reads the Open WebUI database directly.

## Requirements

- Python 3.11+
- Open WebUI 0.11.4 recommended (do not use versions below 0.9.0 in production)
- An Open WebUI API key whose user can read the required knowledge bases

## Configuration

```shell
copy .env.example .env
```

Set at least:

- `OPENWEBUI_BASE_URL` — for example `http://127.0.0.1:3000`;
- `OPENWEBUI_API_KEY` — keep it in a secret manager in production;
- `OPENWEBUI_KNOWLEDGE_ID` — recommended for a single-base deployment.

`OPENWEBUI_ALLOWED_KNOWLEDGE_IDS` is a comma-separated local allowlist. If set, a requested ID must be in the list before any upstream request is made. Without a default ID, callers must supply `knowledge_id` or `knowledge_ids`.

## Run locally

```shell
python -m venv .venv
.venv\\Scripts\\activate       # Windows
# source .venv/bin/activate     # Linux/macOS
python -m pip install -e ".[dev]"
python -m open_webui_mcp --transport stdio
```

The stdio server is intended for local MCP clients. It does not expose an HTTP port.

Run Streamable HTTP for Open WebUI:

```shell
python -m open_webui_mcp --transport http
```

The MCP endpoint is `http://localhost:8000/mcp`. Health endpoints are `/health` and `/ready`. Set `MCP_AUTH_TOKEN` when the endpoint is reachable outside a trusted private network; clients must then send `Authorization: Bearer <token>`.

## Docker

```shell
copy .env.example .env
# edit .env
 docker compose up --build
```

The image runs as an unprivileged `appuser` and serves Streamable HTTP on port 8000.

## Open WebUI setup

1. Create an API key in Open WebUI under the API key settings for a user with read access to the required knowledge base.
2. If API Key Endpoint Restrictions are enabled, allow these read-only routes:
   - `GET /api/v1/knowledge/`
   - `POST /api/v1/retrieval/query/doc`
   - `POST /api/v1/retrieval/query/collection`
3. In Open WebUI open `Settings → Admin → Integrations → External Tool Servers`.
4. Add an MCP server using **Streamable HTTP** and set its URL to `http://<mcp-host>:8000/mcp`.
5. Enable the `search_knowledge` tool.

The server also registers `list_knowledge_bases`, filtered by the local allowlist when one is configured.

## Tool interface

`search_knowledge` accepts `query`, one `knowledge_id` or a non-empty `knowledge_ids` list, and optional retrieval controls (`top_k` from 1 to 20, `hybrid`, `reranker_k`, `relevance_threshold`, `hybrid_bm25_weight`, and `enable_enriched_texts`). It returns only normalized data:

```json
{
  "query": "retention policy",
  "knowledge_ids": ["kb-id"],
  "results": [
    {
      "content": "...",
      "source": "policy.pdf",
      "file_id": "file-id",
      "score": 0.82,
      "metadata": {"page": 4}
    }
  ],
  "count": 1
}
```

The server does not generate an answer or add text to the retrieved fragments.

## Troubleshooting

- **401:** the API key is missing, invalid, expired, or not sent to the requested endpoint. Check `OPENWEBUI_API_KEY` and the Open WebUI API key restrictions.
- **403:** the key's user cannot access the selected knowledge base. Check the user's group and knowledge base permissions.
- **Empty results:** confirm that files are processed and indexed in Open WebUI, and that the selected ID is the knowledge base ID rather than a file ID.
- **MCP connection failure:** verify that Open WebUI can resolve and reach the MCP host, that `/mcp` is used, and that the Streamable HTTP transport—not stdio—is selected.

## Tests and checks

```shell
pytest
ruff check src tests
mypy src tests
```

Live Open WebUI tests are intentionally not enabled by default. The unit and MCP smoke tests use fixtures and mock transports.
