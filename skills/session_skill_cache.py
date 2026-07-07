from __future__ import annotations

from skills.lrfu_cache import LRFUCache, LRFUCandidate


class SessionSkillCache:
    """Session-scoped LRFU cache used for immediate in-conversation routing."""

    def __init__(self, *, decay: float = 0.95, max_entries: int = 200) -> None:
        self._cache = LRFUCache(decay=decay, max_entries=max_entries)

    def touch(self, skill_name: str, *, current_round: int, reward: float = 1.0) -> float:
        return self._cache.touch(skill_name, current_round=current_round, reward=reward)

    def top_candidates(self, *, limit: int, current_round: int) -> list[LRFUCandidate]:
        return self._cache.top_candidates(limit=limit, current_round=current_round)

    def to_dict(self) -> dict:
        return self._cache.to_dict()

    def load_dict(self, data: dict) -> None:
        self._cache.load_dict(data)
