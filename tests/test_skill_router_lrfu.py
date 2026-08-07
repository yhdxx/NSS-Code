from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mycodingagent.relevance.lrfu import LRFUCache, LRFUCandidate
from mycodingagent.skill_runtime.models import SearchResult, SkillRecord
from mycodingagent.skill_runtime.router import SkillRouter, SkillRouterConfig
from mycodingagent.skill_runtime.user_skill_cache import UserSkillCache


def _record(name: str) -> SkillRecord:
    return SkillRecord(
        name=name,
        tool_name=name,
        description=f"{name} description",
        content="",
        source_path=Path(f"{name}.md"),
        content_hash=name,
        updated_at=0.0,
    )


class LRFUCacheTests(unittest.TestCase):
    def test_touch_applies_lazy_decay_and_reward(self) -> None:
        cache = LRFUCache(decay=0.5, max_entries=10)

        cache.touch("skill_a", current_round=1, reward=1.0)
        score = cache.touch("skill_a", current_round=3, reward=1.0)

        self.assertAlmostEqual(score, 1.25)


class UserSkillCacheTests(unittest.TestCase):
    def test_user_table_updates_only_after_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = UserSkillCache(Path(tmp) / "user.sqlite3", decay=0.5, reward=1.0)
            cache.start_session(user_id="u1", session_id="s1")

            cache.record_skill_call(
                user_id="u1",
                session_id="s1",
                skill_name="skill_a",
                session_skill_call_round=1,
            )
            self.assertEqual(cache.top_candidates(user_id="u1", limit=10), [])

            cache.commit_session(user_id="u1", session_id="s1")
            candidates = cache.top_candidates(user_id="u1", limit=10)

            self.assertEqual([item.skill_name for item in candidates], ["skill_a"])
            self.assertAlmostEqual(candidates[0].score, 1.0)

    def test_recover_uncommitted_session_on_next_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "user.sqlite3"
            cache = UserSkillCache(db_path, decay=0.5, reward=1.0)
            cache.start_session(user_id="u1", session_id="interrupted")
            cache.record_skill_call(
                user_id="u1",
                session_id="interrupted",
                skill_name="skill_a",
                session_skill_call_round=1,
            )

            recovered = UserSkillCache(db_path, decay=0.5, reward=1.0)
            recovered.start_session(user_id="u1", session_id="next")
            candidates = recovered.top_candidates(user_id="u1", limit=10)

            self.assertEqual([item.skill_name for item in candidates], ["skill_a"])

    def test_multiple_calls_preserve_frequency_in_session_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = UserSkillCache(Path(tmp) / "user.sqlite3", decay=0.5, reward=1.0)
            cache.start_session(user_id="u1", session_id="s1")
            cache.record_skill_call(
                user_id="u1",
                session_id="s1",
                skill_name="skill_a",
                session_skill_call_round=1,
            )
            cache.record_skill_call(
                user_id="u1",
                session_id="s1",
                skill_name="skill_a",
                session_skill_call_round=3,
            )
            cache.commit_session(user_id="u1", session_id="s1")

            candidates = cache.top_candidates(user_id="u1", limit=10)

            self.assertEqual(candidates[0].skill_name, "skill_a")
            self.assertAlmostEqual(candidates[0].score, 1.25)


class SkillRouterTests(unittest.TestCase):
    def test_router_enforces_top_n_and_retrieval_floor(self) -> None:
        records = {name: _record(name) for name in ["skill_a", "skill_b", "skill_c"]}
        router = SkillRouter(
            SkillRouterConfig(
                top_n=2,
                retrieval_min_ratio=0.5,
                user_weight=0.15,
                session_weight=0.45,
                retrieval_weight=0.40,
            )
        )
        selected = router.select(
            records=records,
            retrieval_results=[
                SearchResult(record=records["skill_c"], score=1.0, keyword_score=0.0, semantic_score=0.0)
            ],
            user_candidates=[LRFUCandidate("skill_a", 10.0)],
            session_candidates=[LRFUCandidate("skill_b", 10.0)],
        )
        selected_names = {record.tool_name for record in selected}

        self.assertLessEqual(len(selected), 2)
        self.assertIn("skill_c", selected_names)


if __name__ == "__main__":
    unittest.main()
