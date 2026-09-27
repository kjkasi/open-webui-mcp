# План: MCP-сервер для базы знаний Open WebUI

## 1. Цель

Создать Python-сервис, который предоставляет MCP-инструмент для семантического поиска по базе знаний Open WebUI и возвращает найденные фрагменты документов с источниками.

Репозиторий сейчас пустой: содержит только `README.md` и `LICENSE`.

## 2. Зафиксированные решения

- **Стек:** Python + FastMCP.
- **Операция MVP:** поиск по содержимому базы знаний, без изменения документов.
- **Доступ к Open WebUI:** API key в заголовке `Authorization: Bearer ...`.
- **Транспорты:**
  - Streamable HTTP — для нативного подключения к Open WebUI.
  - stdio — для локальных MCP-клиентов и разработки.
- **Режим доступа:** read-only.
- **Проверенная локальная версия Open WebUI:** `0.11.4` (`GET /api/version`). В OpenAPI-описании поле `info.version` остаётся `0.1.0`, поэтому версию нужно определять через `/api/version`.
- **Рекомендуемая совместимость:** тестировать в первую очередь с `0.11.4`; для production не использовать версии ниже `0.9.0` из-за известных проблем с ACL retrieval API. Нативная поддержка MCP начинается с `0.6.31`.

## 3. Архитектура

```text
MCP client / Open WebUI
          |
          | MCP: Streamable HTTP или stdio
          v
   open-webui-mcp
     - MCP tools
     - input validation
     - response normalization
     - error mapping
          |
          | HTTPS + Bearer API key
          v
   Open WebUI API
     - GET  /api/v1/knowledge/?page=N
     - POST /api/v1/retrieval/query/doc
     - POST /api/v1/retrieval/query/collection
```

Сервис не подключается напрямую к SQLite/Postgres и не использует внутреннюю схему Open WebUI. Поиск выполняется через API, чтобы Open WebUI сам применял права пользователя API key. Локальная проверка подтвердила, что все три нужных endpoint-а без Bearer token возвращают `401 Not authenticated`.

## 4. MCP-интерфейс MVP

### Основной инструмент: `search_knowledge`

Параметры:

- `query: str` — поисковый запрос;
- `knowledge_id: str | None` — ID одной базы знаний; по умолчанию берётся из конфигурации;
- `knowledge_ids: list[str] | None` — несколько баз знаний, если нужен общий поиск;
- `top_k: int = 5` — число результатов с ограничением сверху, передаётся как upstream `k`;
- `hybrid: bool | None` — запросить hybrid search, если он включён в Open WebUI;
- `reranker_k: int | None` — опционально передать как `k_reranker`;
- `relevance_threshold: float | None` — опционально передать как `r`;
- `hybrid_bm25_weight: float | None` — вес BM25 для hybrid search;
- `enable_enriched_texts: bool | None` — только для поиска по нескольким базам.

Правила валидации:

- `query` не пустой и ограничен по длине;
- задаётся либо `knowledge_id`, либо `knowledge_ids`, либо безопасный default из конфигурации;
- `top_k` ограничен, например `1..20`;
- пустой список баз знаний запрещён.

Нормализованный результат:

```json
{
  "query": "...",
  "knowledge_ids": ["..."],
  "results": [
    {
      "content": "...",
      "source": "document.pdf",
      "file_id": "...",
      "score": 0.82,
      "metadata": {}
    }
  ],
  "count": 1
}
```

Локальный OpenAPI не описывает JSON-схему успешного ответа retrieval endpoint-ов (`schema: {}`). Поэтому фактический ответ нужно получить одним live-запросом с API key и закрепить contract fixture-тестом; до этого нормализатор должен терпимо обрабатывать варианты `documents`, `metadatas`, `distances` и уже плоский список результатов.

### Вспомогательный инструмент: `list_knowledge_bases`

Добавить в MVP или сразу после него, если пользователю нужно выбирать базу по имени. Он вызывает `GET /api/v1/knowledge/` и возвращает только безопасные метаданные: `id`, `name`, `description`, `file_count`. В локальной схеме ответ имеет форму `{ "items": [...], "total": N }`, а endpoint поддерживает параметр `page`. Дополнительный `GET /api/v1/knowledge/search` можно использовать для поиска баз по имени/описанию.

Если сервер должен работать только с одной базой, предпочтительнее не раскрывать список и использовать обязательный `OPENWEBUI_KNOWLEDGE_ID`.

## 5. Конфигурация

Через переменные окружения и `.env.example`:

- `OPENWEBUI_BASE_URL` — URL Open WebUI;
- `OPENWEBUI_API_KEY` — секрет API key;
- `OPENWEBUI_KNOWLEDGE_ID` — база по умолчанию, опционально;
- `OPENWEBUI_ALLOWED_KNOWLEDGE_IDS` — allowlist ID баз, опционально;
- `OPENWEBUI_TIMEOUT_SECONDS` — HTTP timeout;
- `OPENWEBUI_MAX_RETRIES` — число retry для временных upstream-ошибок;
- `MCP_HOST` и `MCP_PORT` — настройки Streamable HTTP;
- `MCP_AUTH_TOKEN` — опциональная защита самого MCP endpoint-а, если он доступен не только во внутренней сети;
- `LOG_LEVEL` — уровень логирования.

Секреты не должны попадать в git, MCP-ответы, исключения или логи. Для production API key должен храниться в secret manager или Docker/Kubernetes secrets.

## 6. Этапы реализации

### Этап 1 — каркас проекта

- Создать `pyproject.toml`.
- Выбрать Python `3.11+`.
- Добавить FastMCP, `httpx`, Pydantic Settings и pytest.
- Настроить форматтер, линтер и type checker.
- Добавить `.env.example`, обновить `.gitignore`.

**Результат:** приложение запускается в stdio-режиме и проходит базовый импорт.

### Этап 2 — клиент Open WebUI API

- Реализовать асинхронный HTTP-клиент с единым timeout.
- Добавить Bearer-аутентификацию.
- Реализовать методы для:
  - получения списка доступных knowledge bases через `GET /api/v1/knowledge/?page=N`;
  - поиска в одной коллекции через `POST /api/v1/retrieval/query/doc`;
  - поиска по нескольким коллекциям через `POST /api/v1/retrieval/query/collection`.
- Формировать upstream payload точно по локальной схеме:
  - single: обязательные `collection_name`, `query`;
  - multi: обязательные `collection_names`, `query`;
  - общие поля: `k`, `k_reranker`, `r`, `hybrid`, `hybrid_bm25_weight`;
  - multi-only: `enable_enriched_texts`.
- Нормализовать ответы в собственные Pydantic-модели.
- Разделить ошибки аутентификации, доступа, валидации, timeout и upstream 5xx.
- Добавить ограниченный retry только для временных ошибок, не для `401/403/4xx`.

### Этап 3 — MCP tools

- Зарегистрировать `search_knowledge`.
- Зарегистрировать `list_knowledge_bases`, если выбран режим с несколькими базами.
- Сформировать короткие описания инструментов, понятные LLM.
- Применить allowlist knowledge ID до вызова Open WebUI API.
- Возвращать результаты с источниками и score без генерации дополнительного текста самим сервером.

### Этап 4 — два транспорта

- Реализовать stdio entrypoint для локальной разработки.
- Реализовать Streamable HTTP endpoint для Open WebUI.
- Зафиксировать URL подключения, например `http://host:port/mcp`.
- Проверить graceful shutdown и корректное закрытие `httpx.AsyncClient`.

Важно: нативная интеграция Open WebUI поддерживает Streamable HTTP. stdio нужен для других MCP-клиентов; чтобы подключить stdio-сервер к Open WebUI, потребуется MCPO или другой HTTP-прокси.

### Этап 5 — тестирование

Unit-тесты:

- валидация входных параметров;
- выбор endpoint для одной/нескольких баз;
- корректная передача Bearer token;
- нормализация разных ответов retrieval API;
- обработка `401`, `403`, `404`, `422`, `429`, `5xx`, timeout;
- allowlist и default knowledge ID;
- отсутствие секрета в логах и ошибках.

Contract/integration-тесты:

- mock HTTP-сервер с fixture-ответами Open WebUI;
- MCP protocol smoke test для stdio;
- MCP protocol smoke test для Streamable HTTP;
- optional live test через `OPENWEBUI_TEST_URL` и `OPENWEBUI_TEST_API_KEY`, отключённый по умолчанию.

### Этап 6 — упаковка и документация

- Добавить Dockerfile с непривилегированным пользователем.
- Добавить `docker-compose.yml` для локального запуска при необходимости.
- Описать запуск обоих транспортов в README.
- Описать создание API key в Open WebUI.
- Описать подключение: `Settings → Admin → Integrations → External Tool Servers → MCP (Streamable HTTP)`.
- Добавить пример вызова инструмента и пример диагностики `401/403`.
- Добавить health/readiness проверку для HTTP-режима, если это поддерживает выбранная версия FastMCP.

## 7. Локальная проверка API

Проверено через `http://127.0.0.1:3000/docs` и `http://127.0.0.1:3000/openapi.json`:

- `/docs` доступен и отдаёт Swagger UI;
- `/api/version` сообщает Open WebUI `0.11.4`;
- `/health` сообщает `{ "status": true }`;
- `GET /api/v1/knowledge/`, `POST /api/v1/retrieval/query/doc` и `POST /api/v1/retrieval/query/collection` защищены Bearer-аутентификацией;
- запросы без токена возвращают `401 {"detail":"Not authenticated"}`;
- retrieval request schemas подтверждены локально: `QueryDocForm` и `QueryCollectionsForm`;
- успешные retrieval responses в OpenAPI намеренно не типизированы, поэтому для окончательного контракта нужен один авторизованный запрос.

Перед реализацией live contract test нужно проверить, что API key имеет доступ к нужным маршрутам. Если в Open WebUI включены API Key Endpoint Restrictions, эти три read-only маршрута должны быть разрешены.

## 8. Критерии готовности MVP

- MCP-клиент видит `search_knowledge`.
- Поиск по одной базе возвращает минимум один нормализованный результат с `content` и `source`.
- Поиск по нескольким базам работает через отдельный collection endpoint.
- Open WebUI подключается к серверу через Streamable HTTP.
- stdio-запуск работает независимо от HTTP-запуска.
- Неверный API key даёт понятную ошибку без раскрытия секрета.
- База, не входящая в allowlist, не передаётся в Open WebUI.
- Unit и protocol smoke-тесты проходят.
- В README есть полностью воспроизводимая инструкция запуска.

## 9. Риски и решения

1. **Изменение API Open WebUI.**
   - Зафиксировать минимально поддерживаемую версию.
   - Держать upstream endpoint и преобразование ответа в одном адаптере.
   - Добавить contract fixtures.

2. **Неверные права API key.**
   - API key наследует права пользователя Open WebUI.
   - Создать отдельного пользователя/группу только для чтения и ограничить доступ к нужным knowledge bases.

3. **Утечка содержимого между базами.**
   - Поддержать allowlist ID.
   - Не разрешать произвольные ID при включённом allowlist.
   - По возможности использовать отдельный API key для каждой зоны доступа.

4. **Пустые результаты.**
   - Документы должны быть обработаны и проиндексированы Open WebUI.
   - В README описать проверку статуса обработки файлов.

5. **Несовместимость транспорта.**
   - Open WebUI использует Streamable HTTP.
   - stdio считать отдельным локальным режимом, не обещать его нативное подключение к Open WebUI.

## 10. Внешние источники

- Open WebUI MCP: https://docs.openwebui.com/features/extensibility/mcp/
- Knowledge Bases API: https://docs.openwebui.com/features/workspace/knowledge/
- API endpoints: https://docs.openwebui.com/reference/api-endpoints/
- API keys: https://docs.openwebui.com/features/authentication-access/api-keys/
- Retrieval router Open WebUI: https://github.com/open-webui/open-webui/blob/main/backend/open_webui/routers/retrieval.py

Следующий шаг после согласования плана — реализовать Этап 1 и сначала сделать вертикальный slice: один инструмент `search_knowledge` для одной базы через Streamable HTTP и stdio.
