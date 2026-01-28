"""Lightweight SemanticSearchEngine delegating responsibilities to services.

This module keeps the orchestration pipeline small and delegates
query processing, context enrichment, scoring and resilience to service
implementations under `core.services`.
"""

from __future__ import annotations

import time
import re
from pathlib import Path
from typing import Any, List

from loguru import logger

from .database import VectorDatabase
from .exceptions import RustPanicError, SearchError
from .git import GitManager
from .guards import RAGGuard
from .models import SearchResult

from .services.resilience import SimpleResilienceManager, ServiceUnavailableError
from .services.reranker import get_global_reranker
from .services.context import DefaultContextService
from .interfaces import ContextService
from .services.query_processor import DefaultQueryProcessor, QueryProcessorService
from .services.scoring import ScoringService
from .services.discovery import DiscoveryService
from .auto_indexer import AutoIndexer, SearchTriggeredIndexer


class SemanticSearchEngine:
    """Orchestrates an async semantic search pipeline using small services."""

    def __init__(
        self,
        database: VectorDatabase,
        project_root: Path,
        similarity_threshold: float = 0.3,
        auto_indexer: AutoIndexer | None = None,
        resilience_manager: SimpleResilienceManager | None = None,
        reranker_service=None,
        reranker_model_name: str | None = None,
        query_processor: QueryProcessorService | None = None,
        context_service: ContextService | None = None,
        scoring_service: ScoringService | None = None,
    ) -> None:
        self.database = database
        self.project_root = project_root
        self.similarity_threshold = similarity_threshold

        self.search_triggered_indexer = (
            SearchTriggeredIndexer(auto_indexer) if auto_indexer is not None else None
        )

        try:
            self.git_manager = GitManager(project_root)
        except Exception:
            self.git_manager = None

        self.rag_guard = RAGGuard()

        self.resilience_manager = resilience_manager or SimpleResilienceManager()
        self.reranker_service = reranker_service or get_global_reranker(reranker_model_name)

        self.context_service: ContextService = context_service or DefaultContextService()
        self.query_processor: QueryProcessorService = (
            query_processor or DefaultQueryProcessor()
        )
        self.scoring_service = scoring_service or ScoringService(self.similarity_threshold)
        self.discovery_service = DiscoveryService(self)

        # Lightweight throttling
        self._last_health_check = 0.0
        self._health_check_interval = 60.0

    @staticmethod
    def _is_rust_panic_error(error: Exception) -> bool:
        """Detect ChromaDB Rust panic errors.

        Args:
            error: Exception to check

        Returns:
            True if this is a Rust panic error
        """
        error_msg = str(error).lower()

        # Check for the specific Rust panic pattern
        # "range start index X out of range for slice of length Y"
        if "range start index" in error_msg and "out of range" in error_msg:
            return True

        # Check for other Rust panic indicators
        rust_panic_patterns = [
            "rust panic",
            "pyo3_runtime.panicexception",
            "thread 'tokio-runtime-worker' panicked",
            "rust/sqlite/src/db.rs",  # Specific to the known ChromaDB issue
        ]

        return any(pattern in error_msg for pattern in rust_panic_patterns)

    @staticmethod
    def _is_corruption_error(error: Exception) -> bool:
        """Detect index corruption errors.

        Args:
            error: Exception to check

        Returns:
            True if this is a corruption error
        """
        error_msg = str(error).lower()

        corruption_indicators = [
            "pickle",
            "unpickling",
            "eof",
            "ran out of input",
            "hnsw",
            "deserialize",
            "corrupt",
        ]

        return any(indicator in error_msg for indicator in corruption_indicators)

    # NOTE: retry/resilience logic has been moved to `ResilienceManager` implementations.

    async def search(
        self,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        similarity_threshold: float | None = None,
        include_context: bool = True,
    ) -> list[SearchResult]:
        """Perform semantic search for code.

        Args:
            query: Search query
            limit: Maximum number of results
            filters: Optional filters (language, file_path, etc.)
            similarity_threshold: Minimum similarity score
            include_context: Whether to include context lines

        Returns:
            List of search results
        """
        if not query.strip():
            return []

        # Throttled health check before search (only every 60 seconds)
        current_time = time.time()
        if current_time - self._last_health_check >= self._health_check_interval:
            try:
                if hasattr(self.database, "health_check"):
                    is_healthy = await self.database.health_check()
                    if not is_healthy:
                        logger.warning("Database health check failed - attempting recovery")
                    self._last_health_check = current_time
            except Exception as e:
                logger.warning(f"Health check failed: {e}")
                self._last_health_check = current_time

        # Auto-reindex check before search
        if self.search_triggered_indexer:
            try:
                await self.search_triggered_indexer.pre_search_hook()
            except Exception as e:
                logger.warning(f"Auto-reindex check failed: {e}")

        threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self.scoring_service.adaptive_threshold(query)
        )

        # Update active files for RAG Guard (Recency Guard)
        if self.git_manager:
            try:
                changed_files = self.git_manager.get_changed_files()
                self.rag_guard.set_active_files([str(f) for f in changed_files])
            except Exception:
                pass

        try:
            # Preprocess query via QueryProcessor
            processed_query = await self.query_processor.process(query)

            # Perform vector search wrapped by resilience manager
            async def _db_search():
                return await self.database.search(
                    query=processed_query,
                    limit=limit,
                    filters=filters,
                    similarity_threshold=threshold,
                )

            try:
                results = await self.resilience_manager.execute(_db_search, max_retries=3, jitter=0.2)
            except ServiceUnavailableError as sue:
                logger.error(f"Resilience manager rejected request: {sue}")
                return []

            # Post-process results (context enrichment) via ContextService
            enhanced_results = []
            for result in results:
                enhanced_result = await self.context_service.get_context(result, include_context)
                # Stale-index detection: if SearchResult has content_hash and DB provides lookup, warn
                try:
                    if getattr(enhanced_result, "content_hash", None) and hasattr(self.database, "get_chunks_by_hash"):
                        matches = await self.database.get_chunks_by_hash(enhanced_result.content_hash)
                        location_match = any(
                            (str(m.file_path) == str(enhanced_result.file_path) and m.start_line == enhanced_result.start_line and m.end_line == enhanced_result.end_line)
                            for m in matches
                        )
                        if not location_match:
                            logger.warning(
                                f"Stale index detected for {enhanced_result.file_path}:{enhanced_result.start_line}-{enhanced_result.end_line} (content_hash mismatch)"
                            )
                except Exception:
                    pass
                enhanced_results.append(enhanced_result)

            # Rerank via injected reranker service
            try:
                ranked_results = await self.reranker_service.rerank(enhanced_results, query)
            except Exception as e:
                logger.warning(f"Reranker service failed, falling back to unranked results: {e}")
                ranked_results = enhanced_results

            # Simple Git-based recency boosting
            if self.git_manager:
                try:
                    recent = set(str(f) for f in self.git_manager.get_changed_files())
                    for r in ranked_results:
                        if str(r.file_path) in recent:
                            r.similarity_score = min(1.0, r.similarity_score + self.scoring_service.boost_source_file)
                except Exception:
                    pass

            # Apply RAG Guard penalties and scope filtering
            ranked_results = self.rag_guard.apply_search_penalties(ranked_results, query)
            ranked_results = self.rag_guard.filter_scope(ranked_results, query)

            # Diversity: limit 3 chunks per file
            file_counts = {}
            diverse_results = []
            for r in ranked_results:
                file_path = str(r.file_path)
                count = file_counts.get(file_path, 0)
                if count < 3:
                    diverse_results.append(r)
                    file_counts[file_path] = count + 1

            # Final sort and rank update
            diverse_results.sort(key=lambda r: r.similarity_score, reverse=True)
            for i, result in enumerate(diverse_results):
                result.rank = i + 1

            # Efficiency Pipeline Logging
            if diverse_results:
                try:
                    total_file_lines = 0
                    delivered_lines = 0
                    unique_files = set()

                    for r in diverse_results:
                        unique_files.add(r.file_path)
                        delivered_lines += (r.end_line - r.start_line + 1)

                    for f_path in unique_files:
                        if f_path in self._file_cache:
                            total_file_lines += len(self._file_cache[f_path])
                        else:
                            total_file_lines += delivered_lines * 5

                    savings = 0
                    if total_file_lines > 0:
                        savings = int((1 - (delivered_lines / total_file_lines)) * 100)

                    logger.info(f"[VERİMLİLİK] 📉 AI Bağlamı Optimize Edildi: {total_file_lines} satır → {delivered_lines} satır (%{savings} Token tasarrufu).")
                    logger.info(f"[ZEKA] 🎯 Reranker applied: {len(unique_files)} dosya tarandı, en alakalı {len(diverse_results)} kod parçası seçildi.")
                except Exception:
                    pass

            logger.debug(
                f"Search for '{query}' with threshold {threshold:.3f} returned {len(diverse_results)} results"
            )

            return diverse_results

        except (RustPanicError, SearchError):
            # These errors are already properly formatted with user guidance
            raise
        except Exception as e:
            # Unexpected error - log and return safe fallback
            logger.error(f"Unexpected search error for query '{query}': {e}")
            return []

    # Delegate discovery helpers to DiscoveryService (keeps this module small)


