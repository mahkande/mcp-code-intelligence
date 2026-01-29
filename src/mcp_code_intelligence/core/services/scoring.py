
"""ScoringService: adaptive thresholding and small scoring helpers."""

from typing import Optional


class ScoringService:
    """Encapsulates scoring constants and adaptive threshold logic."""

    def __init__(self, base_threshold: float = 0.3) -> None:
        self.base_threshold = base_threshold

        # Tunable boosts / penalties
        self.boost_source_file = 0.05
        self.penalty_stale_index = 0.15

    def adaptive_threshold(self, query: str, override: Optional[float] = None) -> float:
        """Return an adaptive similarity threshold for `query`.

        This is a lightweight heuristic: longer queries are usually more
        informative, so lower the threshold slightly for short queries to
        increase recall.
        """
        if override is not None:
            return override

        length = len(query or "")
        if length < 20:
            return max(0.15, self.base_threshold - 0.05)
        if length > 200:
            return min(0.6, self.base_threshold + 0.1)
        return self.base_threshold
