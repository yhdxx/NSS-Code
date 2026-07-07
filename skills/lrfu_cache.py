from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LRFUEntry:
    skill_name: str
    score: float = 0.0
    last_update_round: int = 0


@dataclass(frozen=True)
class LRFUCandidate:
    skill_name: str
    score: float


class LRFUCache:
    """In-memory time-decayed LRFU cache with lazy score updates."""

    def __init__(self, *, decay: float = 0.95, max_entries: int = 200) -> None:
        self.decay = decay
        self.max_entries = max(1, max_entries)
        self._entries: dict[str, LRFUEntry] = {}

    def touch(self, skill_name: str, *, current_round: int, reward: float = 1.0) -> float:
        entry = self._entries.get(skill_name)
        if entry is None:
            entry = LRFUEntry(skill_name=skill_name)
            self._entries[skill_name] = entry
        entry.score = self.decayed_score(
            entry.score,
            last_update_round=entry.last_update_round,
            current_round=current_round,
            decay=self.decay,
        ) + reward
        entry.last_update_round = max(current_round, entry.last_update_round)
        self._prune_if_needed(current_round=current_round)
        return entry.score

    def get_score(self, skill_name: str, *, current_round: int) -> float:
        entry = self._entries.get(skill_name)
        if entry is None:
            return 0.0
        entry.score = self.decayed_score(
            entry.score,
            last_update_round=entry.last_update_round,
            current_round=current_round,
            decay=self.decay,
        )
        entry.last_update_round = max(current_round, entry.last_update_round)
        return entry.score

    def top_candidates(self, *, limit: int, current_round: int) -> list[LRFUCandidate]:
        if limit <= 0:
            return []
        candidates = [
            LRFUCandidate(skill_name=name, score=self.get_score(name, current_round=current_round))
            for name in list(self._entries)
        ]
        candidates.sort(key=lambda item: (-item.score, item.skill_name))
        return candidates[:limit]

    def to_dict(self) -> dict:
        return {
            "decay": self.decay,
            "max_entries": self.max_entries,
            "entries": [
                {
                    "skill_name": entry.skill_name,
                    "score": entry.score,
                    "last_update_round": entry.last_update_round,
                }
                for entry in self._entries.values()
            ],
        }

    def load_dict(self, data: dict) -> None:
        self.decay = float(data.get("decay", self.decay))
        self.max_entries = max(1, int(data.get("max_entries", self.max_entries)))
        entries: dict[str, LRFUEntry] = {}
        for item in data.get("entries", []):
            if not isinstance(item, dict):
                continue
            skill_name = str(item.get("skill_name", "")).strip()
            if not skill_name:
                continue
            entries[skill_name] = LRFUEntry(
                skill_name=skill_name,
                score=float(item.get("score", 0.0)),
                last_update_round=int(item.get("last_update_round", 0)),
            )
        self._entries = entries

    @staticmethod
    def decayed_score(
        score: float,
        *,
        last_update_round: int,
        current_round: int,
        decay: float,
    ) -> float:
        delta = max(0, current_round - last_update_round)
        if delta == 0 or score <= 0:
            return score
        return score * (decay ** delta)

    def _prune_if_needed(self, *, current_round: int) -> None:
        if len(self._entries) <= self.max_entries:
            return
        keep = {
            candidate.skill_name
            for candidate in self.top_candidates(limit=self.max_entries, current_round=current_round)
        }
        self._entries = {
            name: entry
            for name, entry in self._entries.items()
            if name in keep
        }
