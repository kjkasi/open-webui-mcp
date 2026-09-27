from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SearchRequest(BaseModel):
    """Validated public input for the search tool."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    knowledge_id: str | None = None
    knowledge_ids: list[str] | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    hybrid: bool | None = None
    reranker_k: int | None = Field(default=None, ge=1, le=100)
    relevance_threshold: float | None = Field(default=None, ge=0, le=1)
    hybrid_bm25_weight: float | None = Field(default=None, ge=0, le=1)
    enable_enriched_texts: bool | None = None

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value

    @field_validator("knowledge_id", mode="before")
    @classmethod
    def normalize_knowledge_id(cls, value: object) -> object:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @field_validator("knowledge_ids", mode="before")
    @classmethod
    def normalize_knowledge_ids(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("knowledge_ids must be a list")
        result = [str(item).strip() for item in value]
        if not result or any(not item for item in result):
            raise ValueError("knowledge_ids must not be empty")
        return result

    @model_validator(mode="after")
    def validate_selection(self) -> SearchRequest:
        if self.knowledge_id and self.knowledge_ids:
            raise ValueError("set either knowledge_id or knowledge_ids, not both")
        return self


class KnowledgeBaseSummary(BaseModel):
    """Safe, non-sensitive knowledge base metadata exposed by the MCP tool."""

    id: str
    name: str
    description: str | None = None
    file_count: int | None = None


class SearchResult(BaseModel):
    content: str
    source: str | None = None
    file_id: str | None = None
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    knowledge_ids: list[str]
    results: list[SearchResult]
    count: int

    @model_validator(mode="after")
    def set_count(self) -> SearchResponse:
        self.count = len(self.results)
        return self
