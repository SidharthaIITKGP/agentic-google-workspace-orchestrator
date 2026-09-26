import asyncio
import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Any
from uuid import UUID
from weakref import WeakKeyDictionary

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import RedisCache
from app.db.models import DocumentChunk, SyncState, WorkspaceItem
from app.retrieval.relevance import select_relevant_candidates
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.laya_reranker import CandidateReranker


@dataclass(frozen=True)
class WorkspaceSearchFilters:
    services: list[str] | None = None
    sender: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    mime_type: str | None = None
    attendee: str | None = None


@dataclass(frozen=True)
class WorkspaceSearchResult:
    workspace_item_id: UUID
    service: str
    external_resource_id: str
    title: str
    chunk_text: str
    score: float
    metadata: dict[str, Any]
    indexed_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "workspace_item_id": str(self.workspace_item_id),
            "service": self.service,
            "external_resource_id": self.external_resource_id,
            "title": self.title,
            "chunk_text": self.chunk_text,
            "score": self.score,
            "metadata": self.metadata,
            "indexed_at": self.indexed_at.isoformat(),
        }


@dataclass(frozen=True)
class WorkspaceSearchResponse:
    results: list[WorkspaceSearchResult]
    duration_ms: float
    embedding_duration_ms: float = 0.0
    database_duration_ms: float = 0.0
    embedding_cache_hit: bool = False
    sync_states: dict[str, dict[str, object]] = field(default_factory=dict)
    reranking_provider: str = "disabled"
    reranking_duration_ms: float = 0.0
    reranking_fallback_used: bool = False
    reranking_model: str | None = None
    reranking_input_tokens: int | None = None


_MAX_PROCESS_EMBEDDINGS = 128
_PROCESS_EMBEDDINGS: OrderedDict[str, list[float]] = OrderedDict()


@dataclass
class _EmbeddingFlightState:
    guard: asyncio.Lock = field(default_factory=asyncio.Lock)
    flights: dict[str, asyncio.Lock] = field(default_factory=dict)


_EMBEDDING_FLIGHT_STATES: WeakKeyDictionary[
    asyncio.AbstractEventLoop, _EmbeddingFlightState
] = WeakKeyDictionary()


class HybridWorkspaceSearch:
    def __init__(
        self,
        session: AsyncSession,
        embeddings: EmbeddingProvider,
        cache: RedisCache | None = None,
        cache_ttl_seconds: int = 3600,
        reranker: CandidateReranker | None = None,
    ) -> None:
        self._session = session
        self._embeddings = embeddings
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds
        self._reranker = reranker

    async def search(
        self,
        user_id: UUID,
        query: str,
        top_k: int = 5,
        filters: WorkspaceSearchFilters | None = None,
    ) -> WorkspaceSearchResponse:
        if not query.strip():
            raise ValueError("query must be non-empty")
        if isinstance(top_k, bool) or not 1 <= top_k <= 50:
            raise ValueError("top_k must be between 1 and 50")
        started = perf_counter()
        embedding_started = perf_counter()
        query_embedding, embedding_cache_hit = await self._query_embedding_with_metadata(
            user_id, query
        )
        embedding_duration_ms = (perf_counter() - embedding_started) * 1000
        filters = filters or WorkspaceSearchFilters()

        cosine_distance = DocumentChunk.embedding.cosine_distance(query_embedding)
        keyword_rank = func.ts_rank_cd(
            func.to_tsvector("simple", DocumentChunk.text),
            func.plainto_tsquery("simple", query),
        )
        score = ((1.0 - cosine_distance) * 0.75 + keyword_rank * 0.25).label("score")
        conditions = [
            DocumentChunk.user_id == user_id,
            WorkspaceItem.user_id == user_id,
            WorkspaceItem.deleted_at.is_(None),
        ]
        if filters.services:
            conditions.append(WorkspaceItem.service.in_(filters.services))
        if filters.sender:
            conditions.append(WorkspaceItem.resource_metadata["sender"].astext.ilike(f"%{filters.sender}%"))
        if filters.mime_type:
            conditions.append(WorkspaceItem.resource_metadata["mime_type"].astext == filters.mime_type)
        if filters.attendee:
            conditions.append(
                WorkspaceItem.resource_metadata["attendees"].contains([filters.attendee])
            )
        date_value = func.coalesce(
            WorkspaceItem.resource_metadata["start"].astext,
            WorkspaceItem.resource_metadata["date"].astext,
            WorkspaceItem.resource_metadata["modified_time"].astext,
        )
        if filters.date_from:
            conditions.append(date_value >= filters.date_from)
        if filters.date_to:
            conditions.append(date_value < filters.date_to)

        candidate_pool_size = max(
            top_k * 5,
            self._reranker.candidate_cap if self._reranker is not None else top_k,
        )
        statement = (
            select(
                WorkspaceItem.id,
                WorkspaceItem.service,
                WorkspaceItem.external_resource_id,
                WorkspaceItem.title,
                DocumentChunk.text,
                WorkspaceItem.resource_metadata,
                WorkspaceItem.indexed_at,
                score,
            )
            .join(WorkspaceItem, WorkspaceItem.id == DocumentChunk.workspace_item_id)
            .where(and_(*conditions))
            .order_by(desc(score))
            .limit(candidate_pool_size)
        )
        database_started = perf_counter()
        rows = (await self._session.execute(statement)).all()
        database_duration_ms = (perf_counter() - database_started) * 1000
        requested_services = set(filters.services) if filters.services else {
            "gmail",
            "google_calendar",
            "google_drive",
        }
        state_rows = (
            list(
                (
                    await self._session.scalars(
                        select(SyncState).where(
                            SyncState.user_id == user_id,
                            SyncState.service.in_(requested_services),
                        )
                    )
                ).all()
            )
            if hasattr(self._session, "scalars")
            else []
        )
        sync_states = {
            state.service: {
                "status": state.status,
                "last_successful_sync": state.last_successful_sync,
            }
            for state in state_rows
        }
        for service in requested_services:
            sync_states.setdefault(
                service,
                {"status": "missing", "last_successful_sync": None},
            )
        results: list[WorkspaceSearchResult] = []
        seen_items: set[UUID] = set()
        for row in rows:
            if row.id in seen_items:
                continue
            seen_items.add(row.id)
            results.append(WorkspaceSearchResult(
                workspace_item_id=row.id,
                service=row.service,
                external_resource_id=row.external_resource_id,
                title=row.title,
                chunk_text=row.text,
                score=float(row.score),
                metadata=dict(row.resource_metadata),
                indexed_at=row.indexed_at,
            ))
            if len(results) == candidate_pool_size:
                break
        hybrid_results = select_relevant_candidates(
            results,
            query,
            top_k=(max(top_k, self._reranker.candidate_cap) if self._reranker else top_k),
            requested_services=set(filters.services) if filters.services else None,
        )
        reranking_provider = "disabled"
        reranking_duration_ms = 0.0
        reranking_fallback_used = False
        reranking_model = None
        reranking_input_tokens = None
        if self._reranker is not None:
            reranked = await self._reranker.rerank(query, hybrid_results, top_k)
            final_results = reranked.results
            reranking_provider = reranked.provider
            reranking_duration_ms = reranked.latency_ms
            reranking_fallback_used = reranked.fallback_used
            reranking_model = reranked.model
            reranking_input_tokens = reranked.input_tokens
        else:
            final_results = hybrid_results[:top_k]
        return WorkspaceSearchResponse(
            results=final_results,
            duration_ms=(perf_counter() - started) * 1000,
            embedding_duration_ms=embedding_duration_ms,
            database_duration_ms=database_duration_ms,
            embedding_cache_hit=embedding_cache_hit,
            sync_states=sync_states,
            reranking_provider=reranking_provider,
            reranking_duration_ms=reranking_duration_ms,
            reranking_fallback_used=reranking_fallback_used,
            reranking_model=reranking_model,
            reranking_input_tokens=reranking_input_tokens,
        )

    async def _query_embedding(self, user_id: UUID, query: str) -> list[float]:
        embedding, _ = await self._query_embedding_with_metadata(user_id, query)
        return embedding

    async def _query_embedding_with_metadata(
        self, user_id: UUID, query: str
    ) -> tuple[list[float], bool]:
        normalized_query = " ".join(query.casefold().split())
        model_name = str(
            getattr(
                self._embeddings,
                "model_name",
                type(self._embeddings).__qualname__,
            )
        )
        model_digest = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:16]
        query_digest = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()
        cache_key = (
            f"retrieval:embedding:{user_id}:{model_digest}:"
            f"{self._embeddings.dimensions}:{query_digest}"
        )
        cached = _process_embedding(cache_key)
        if cached is not None:
            return cached, True
        if self._cache is not None:
            cached = await self._cache.get_json(cache_key)
            if isinstance(cached, list) and len(cached) == self._embeddings.dimensions:
                embedding = [float(value) for value in cached]
                _remember_process_embedding(cache_key, embedding)
                return embedding, True

        flight_state = _embedding_flight_state()
        lock = await _embedding_flight(flight_state, cache_key)
        try:
            async with lock:
                cached = _process_embedding(cache_key)
                if cached is not None:
                    return cached, True
                if self._cache is not None:
                    cached_value = await self._cache.get_json(cache_key)
                    if (
                        isinstance(cached_value, list)
                        and len(cached_value) == self._embeddings.dimensions
                    ):
                        embedding = [float(value) for value in cached_value]
                        _remember_process_embedding(cache_key, embedding)
                        return embedding, True
                embedding = await asyncio.to_thread(
                    self._embeddings.embed_text, normalized_query
                )
                _remember_process_embedding(cache_key, embedding)
                if self._cache is not None:
                    await self._cache.set_json(
                        cache_key, embedding, self._cache_ttl_seconds
                    )
                return embedding, False
        finally:
            async with flight_state.guard:
                if flight_state.flights.get(cache_key) is lock:
                    flight_state.flights.pop(cache_key, None)


def _embedding_flight_state() -> _EmbeddingFlightState:
    loop = asyncio.get_running_loop()
    state = _EMBEDDING_FLIGHT_STATES.get(loop)
    if state is None:
        state = _EmbeddingFlightState()
        _EMBEDDING_FLIGHT_STATES[loop] = state
    return state


async def _embedding_flight(
    state: _EmbeddingFlightState,
    cache_key: str,
) -> asyncio.Lock:
    async with state.guard:
        return state.flights.setdefault(cache_key, asyncio.Lock())


def _process_embedding(cache_key: str) -> list[float] | None:
    embedding = _PROCESS_EMBEDDINGS.get(cache_key)
    if embedding is None:
        return None
    _PROCESS_EMBEDDINGS.move_to_end(cache_key)
    return list(embedding)


def _remember_process_embedding(cache_key: str, embedding: list[float]) -> None:
    _PROCESS_EMBEDDINGS[cache_key] = list(embedding)
    _PROCESS_EMBEDDINGS.move_to_end(cache_key)
    while len(_PROCESS_EMBEDDINGS) > _MAX_PROCESS_EMBEDDINGS:
        _PROCESS_EMBEDDINGS.popitem(last=False)
