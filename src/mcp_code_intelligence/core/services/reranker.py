"""Reranker service implementation with lazy model loading.

Implements a `RerankerService` compatible class that loads heavy HF/Jina
models lazily and provides an async `rerank` method. If transformers are
not available, falls back to a no-op re-ranker.
"""
from __future__ import annotations

import asyncio
from typing import Optional, List

from ..interfaces import RerankerService
from ..models import SearchResult


try:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    import torch
    HAS_TRANSFORMERS = True
except Exception:
    HAS_TRANSFORMERS = False


class LazyHFReRanker(RerankerService):
    """HF-based reranker that lazy-loads model/tokenizer on first use.

    Use a global singleton via `get_global_reranker` to avoid repeated
    model initializations when `SemanticSearchEngine` instances are created.
    """

    def __init__(self, model_name: Optional[str] = None, device: Optional[str] = None):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._tokenizer = None

    def _ensure_loaded(self) -> None:
        if not HAS_TRANSFORMERS or not self.model_name:
            return
        if self._model is None or self._tokenizer is None:
            # Import locally to keep discovery light-weight
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            # Move to device if torch available and device resolved
            if hasattr(self._model, "to"):
                dev = self.device or ("cuda" if hasattr(__import__("torch"), "cuda") and __import__("torch").cuda.is_available() else "cpu")
                try:
                    self._model.to(dev)
                except Exception:
                    pass

    async def rerank(self, results: List[SearchResult], query: str) -> List[SearchResult]:
        # No-op if transformers or model not configured
        if not HAS_TRANSFORMERS or not self.model_name:
            return results

        loop = asyncio.get_event_loop()

        def _sync_rerank():
            try:
                self._ensure_loaded()
                if self._model is None or self._tokenizer is None:
                    return results

                # Prepare pairwise inputs: [query || candidate_text]
                inputs = []
                for r in results:
                    # Heuristic: prefer short preview if present, else file path
                    preview = getattr(r, "preview_text", None) or getattr(r, "text", None) or str(getattr(r, "file_path", ""))
                    inputs.append(f"{query} </s> {preview}")

                enc = self._tokenizer(inputs, truncation=True, padding=True, return_tensors="pt")
                # Move tensors to model device if possible
                try:
                    import torch as _torch
                    device = next(self._model.parameters()).device
                    enc = {k: v.to(device) for k, v in enc.items()}
                    with _torch.no_grad():
                        logits = self._model(**enc).logits
                        # Assume binary classification; use positive class prob if present
                        import torch.nn.functional as F
                        probs = F.softmax(logits, dim=-1)
                        scores = probs[:, -1].cpu().numpy()
                except Exception:
                    # Fallback: treat logits as scores if any
                    try:
                        logits = self._model(**enc).logits
                        scores = logits.mean(dim=-1).cpu().numpy()
                    except Exception:
                        return results

                scored = list(zip(scores.tolist(), results))
                scored.sort(key=lambda x: x[0], reverse=True)
                return [r for _, r in scored]
            except Exception:
                return results

        ranked = await loop.run_in_executor(None, _sync_rerank)
        return ranked


_GLOBAL_RERANKER: Optional[LazyHFReRanker] = None


def get_global_reranker(model_name: Optional[str] = None) -> RerankerService:
    """Return a process-global singleton reranker. If already created,
    model_name is ignored to avoid reloading conflicting models.
    """
    global _GLOBAL_RERANKER
    if _GLOBAL_RERANKER is None:
        _GLOBAL_RERANKER = LazyHFReRanker(model_name=model_name)
    return _GLOBAL_RERANKER


class NoopReranker(RerankerService):
    async def rerank(self, results: List[SearchResult], query: str) -> List[SearchResult]:
        return results
