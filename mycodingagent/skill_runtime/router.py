from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from mycodingagent.relevance.lrfu import LRFUCandidate
from mycodingagent.skill_runtime.models import SearchResult, SkillRecord


@dataclass(frozen=True)
class SkillRouterConfig:
    top_n: int = 20
    retrieval_min_ratio: float = 0.4
    user_weight: float = 0.15
    session_weight: float = 0.45
    retrieval_weight: float = 0.40
    pinned_bonus: float = 1.0


@dataclass
class _RouterCandidate:
    record: SkillRecord
    user_score: float = 0.0
    session_score: float = 0.0
    retrieval_score: float = 0.0
    retrieval_rank: int | None = None
    pinned: bool = False
    combined_score: float = 0.0

    @property
    def from_retrieval(self) -> bool:
        return self.retrieval_rank is not None


class SkillRouter:
    """Fuse retrieval, session, and user Skill candidates into a bounded TopN."""

    def __init__(self, config: SkillRouterConfig) -> None:
        self.config = config

    def select(
        self,
        *,
        records: dict[str, SkillRecord],
        retrieval_results: list[SearchResult],
        user_candidates: list[LRFUCandidate],
        session_candidates: list[LRFUCandidate],
        pinned_names: set[str],
    ) -> list[SkillRecord]:
        if not records or self.config.top_n <= 0:
            return []

        candidates: dict[str, _RouterCandidate] = {}
        self._merge_retrieval(candidates, records=records, retrieval_results=retrieval_results)
        self._merge_lrfu(candidates, records=records, source=user_candidates, source_name="user")
        self._merge_lrfu(candidates, records=records, source=session_candidates, source_name="session")
        for name in pinned_names:
            record = records.get(name)
            if record is None:
                continue
            candidates.setdefault(name, _RouterCandidate(record=record)).pinned = True

        if not candidates:
            return []

        self._score_candidates(list(candidates.values()))
        ordered = sorted(candidates.values(), key=self._sort_key)
        selected = ordered[: self.config.top_n]
        selected = self._enforce_retrieval_floor(selected, candidates)
        selected.sort(key=self._sort_key)
        return [candidate.record for candidate in selected[: self.config.top_n]]

    def _merge_retrieval(
        self,
        candidates: dict[str, _RouterCandidate],
        *,
        records: dict[str, SkillRecord],
        retrieval_results: list[SearchResult],
    ) -> None:
        seen: set[str] = set()
        rank = 0
        for result in retrieval_results:
            name = result.record.tool_name
            if name in seen:
                continue
            record = records.get(name)
            if record is None:
                continue
            seen.add(name)
            rank += 1
            candidate = candidates.setdefault(name, _RouterCandidate(record=record))
            candidate.retrieval_rank = rank
            candidate.retrieval_score = 1.0 / rank

    def _merge_lrfu(
        self,
        candidates: dict[str, _RouterCandidate],
        *,
        records: dict[str, SkillRecord],
        source: list[LRFUCandidate],
        source_name: str,
    ) -> None:
        max_score = max((item.score for item in source), default=0.0)
        for item in source:
            record = records.get(item.skill_name)
            if record is None:
                continue
            normalized = item.score / max_score if max_score > 0 else 0.0
            candidate = candidates.setdefault(item.skill_name, _RouterCandidate(record=record))
            if source_name == "user":
                candidate.user_score = normalized
            elif source_name == "session":
                candidate.session_score = normalized

    def _score_candidates(self, candidates: list[_RouterCandidate]) -> None:
        for candidate in candidates:
            candidate.combined_score = (
                self.config.user_weight * candidate.user_score
                + self.config.session_weight * candidate.session_score
                + self.config.retrieval_weight * candidate.retrieval_score
            )
            if candidate.pinned:
                candidate.combined_score += self.config.pinned_bonus

    def _enforce_retrieval_floor(
        self,
        selected: list[_RouterCandidate],
        candidates: dict[str, _RouterCandidate],
    ) -> list[_RouterCandidate]:
        retrieval_candidates = sorted(
            [candidate for candidate in candidates.values() if candidate.from_retrieval],
            key=lambda item: item.retrieval_rank or 0,
        )
        if not retrieval_candidates or self.config.retrieval_min_ratio <= 0:
            return selected
        floor = min(
            len(retrieval_candidates),
            max(1, ceil(self.config.top_n * self.config.retrieval_min_ratio)),
        )
        selected_by_name = {candidate.record.tool_name: candidate for candidate in selected}
        selected_retrieval_count = sum(1 for candidate in selected if candidate.from_retrieval)
        for retrieval_candidate in retrieval_candidates:
            if selected_retrieval_count >= floor:
                break
            name = retrieval_candidate.record.tool_name
            if name in selected_by_name:
                continue
            if len(selected) < self.config.top_n:
                selected.append(retrieval_candidate)
                selected_by_name[name] = retrieval_candidate
                selected_retrieval_count += 1
                continue
            replaceable = [
                candidate
                for candidate in selected
                if not candidate.pinned and not candidate.from_retrieval
            ]
            if not replaceable:
                break
            victim = min(replaceable, key=lambda item: (item.combined_score, item.record.tool_name))
            selected.remove(victim)
            selected_by_name.pop(victim.record.tool_name, None)
            selected.append(retrieval_candidate)
            selected_by_name[name] = retrieval_candidate
            selected_retrieval_count += 1
        return selected

    def _sort_key(self, candidate: _RouterCandidate) -> tuple[float, int, float, float, str]:
        return (
            -candidate.combined_score,
            -int(candidate.from_retrieval),
            -candidate.session_score,
            -candidate.user_score,
            candidate.record.tool_name,
        )
