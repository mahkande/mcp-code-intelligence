"""Async interfaces (protocols) for core services.

Defines lightweight async Protocols used to break apart the large
SemanticSearchEngine responsibilities into testable services.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable, Callable, Awaitable, Any

from .models import SearchResult


@runtime_checkable
class QueryProcessor(Protocol):
    """Preprocess and expand queries before they are sent to the DB."""

    async def process(self, query: str) -> str:
        """Return a normalized/expanded query string."""


@runtime_checkable
class RerankerService(Protocol):
    """Re-rank search results (neural or heuristic).

    Implementations should be safe to construct cheaply; heavy model
    loading should be done lazily inside the implementation.
    """

    async def rerank(self, results: list[SearchResult], query: str) -> list[SearchResult]:
        """Return a re-ordered list of `SearchResult` instances."""


@runtime_checkable
class ResilienceManager(Protocol):
    """Encapsulates retry / backoff / circuit-breaker logic for fragile ops."""

    async def execute(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> Any:
        """Execute `func(*args, **kwargs)` with resilience policies applied.

        Should raise the original exception if retries exhausted and the
        error is non-recoverable.
        """
