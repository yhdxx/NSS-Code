from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from mycodingagent.relevance.lrfu import LRFUCache, LRFUCandidate


class UserSkillCache:
    """Persistent user LRFU cache with deferred session commits.

    The main user table is updated only at graceful session end or during
    startup recovery. Individual skill invocations are persisted to pending
    session rows so an interrupted process can be reconciled on the next run.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        decay: float = 0.95,
        reward: float = 1.0,
        max_entries: int = 1000,
    ) -> None:
        self.db_path = db_path
        self.decay = decay
        self.reward = reward
        self.max_entries = max(1, max_entries)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def start_session(self, *, user_id: str, session_id: str) -> None:
        self.recover_uncommitted(user_id=user_id)
        base_round = self.get_user_skill_call_round(user_id=user_id)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO pending_skill_sessions (
                    user_id, session_id, base_user_skill_call_round,
                    session_skill_call_round, committed, created_at, updated_at
                )
                VALUES (?, ?, ?, 0, 0, ?, ?)
                """,
                (user_id, session_id, base_round, now, now),
            )

    def get_user_skill_call_round(self, *, user_id: str) -> int:
        with self._connect() as conn:
            return self._get_user_skill_call_round(conn, user_id=user_id)

    def record_skill_call(
        self,
        *,
        user_id: str,
        session_id: str,
        skill_name: str,
        session_skill_call_round: int,
    ) -> None:
        if session_skill_call_round <= 0:
            return
        now = time.time()
        with self._connect() as conn:
            session = conn.execute(
                """
                SELECT base_user_skill_call_round, session_skill_call_round
                FROM pending_skill_sessions
                WHERE user_id = ? AND session_id = ? AND committed = 0
                """,
                (user_id, session_id),
            ).fetchone()
            if session is None:
                base_round = self._get_user_skill_call_round(conn, user_id=user_id)
                conn.execute(
                    """
                    INSERT INTO pending_skill_sessions (
                        user_id, session_id, base_user_skill_call_round,
                        session_skill_call_round, committed, created_at, updated_at
                    )
                    VALUES (?, ?, ?, 0, 0, ?, ?)
                    """,
                    (user_id, session_id, base_round, now, now),
                )

            row = conn.execute(
                """
                SELECT last_session_skill_call_round, call_count, session_lrfu_score
                FROM pending_skill_updates
                WHERE user_id = ? AND session_id = ? AND skill_name = ? AND committed = 0
                """,
                (user_id, session_id, skill_name),
            ).fetchone()
            if row is None:
                last_round = 0
                call_count = 0
                session_score = 0.0
            else:
                last_round = int(row[0])
                call_count = int(row[1])
                session_score = float(row[2])

            session_score = LRFUCache.decayed_score(
                session_score,
                last_update_round=last_round,
                current_round=session_skill_call_round,
                decay=self.decay,
            ) + self.reward
            call_count += 1
            conn.execute(
                """
                INSERT INTO pending_skill_updates (
                    user_id, session_id, skill_name, last_session_skill_call_round,
                    call_count, session_lrfu_score, committed, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(user_id, session_id, skill_name) DO UPDATE SET
                    last_session_skill_call_round=excluded.last_session_skill_call_round,
                    call_count=excluded.call_count,
                    session_lrfu_score=excluded.session_lrfu_score,
                    updated_at=excluded.updated_at
                """,
                (
                    user_id,
                    session_id,
                    skill_name,
                    session_skill_call_round,
                    call_count,
                    session_score,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE pending_skill_sessions
                SET session_skill_call_round = MAX(session_skill_call_round, ?),
                    updated_at = ?
                WHERE user_id = ? AND session_id = ?
                """,
                (session_skill_call_round, now, user_id, session_id),
            )

    def commit_session(self, *, user_id: str, session_id: str) -> None:
        with self._connect() as conn:
            self._commit_session(conn, user_id=user_id, session_id=session_id)

    def recover_uncommitted(self, *, user_id: str) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id
                FROM pending_skill_sessions
                WHERE user_id = ? AND committed = 0
                ORDER BY created_at, session_id
                """,
                (user_id,),
            ).fetchall()
            for (session_id,) in rows:
                self._commit_session(conn, user_id=user_id, session_id=str(session_id))

    def top_candidates(self, *, user_id: str, limit: int) -> list[LRFUCandidate]:
        if limit <= 0:
            return []
        current_round = self.get_user_skill_call_round(user_id=user_id)
        candidate_limit = max(limit * 4, limit)
        with self._connect() as conn:
            by_score = conn.execute(
                """
                SELECT skill_name, score, last_update_round
                FROM user_skill_lrfu
                WHERE user_id = ?
                ORDER BY score DESC, skill_name
                LIMIT ?
                """,
                (user_id, candidate_limit),
            ).fetchall()
            by_recent = conn.execute(
                """
                SELECT skill_name, score, last_update_round
                FROM user_skill_lrfu
                WHERE user_id = ?
                ORDER BY last_update_round DESC, skill_name
                LIMIT ?
                """,
                (user_id, candidate_limit),
            ).fetchall()
            rows_by_name: dict[str, tuple[str, float, int]] = {}
            for skill_name, score, last_round in [*by_score, *by_recent]:
                rows_by_name[str(skill_name)] = (str(skill_name), float(score), int(last_round))

            candidates: list[LRFUCandidate] = []
            for skill_name, score, last_round in rows_by_name.values():
                decayed = LRFUCache.decayed_score(
                    score,
                    last_update_round=last_round,
                    current_round=current_round,
                    decay=self.decay,
                )
                if decayed != score or last_round != current_round:
                    conn.execute(
                        """
                        UPDATE user_skill_lrfu
                        SET score = ?, last_update_round = ?
                        WHERE user_id = ? AND skill_name = ?
                        """,
                        (decayed, current_round, user_id, skill_name),
                    )
                candidates.append(LRFUCandidate(skill_name=skill_name, score=decayed))

        candidates.sort(key=lambda item: (-item.score, item.skill_name))
        return candidates[:limit]

    def _commit_session(self, conn: sqlite3.Connection, *, user_id: str, session_id: str) -> None:
        session = conn.execute(
            """
            SELECT base_user_skill_call_round, session_skill_call_round
            FROM pending_skill_sessions
            WHERE user_id = ? AND session_id = ? AND committed = 0
            """,
            (user_id, session_id),
        ).fetchone()
        if session is None:
            return
        base_round = int(session[0])
        total_rounds = int(session[1])
        now = time.time()
        if total_rounds <= 0:
            self._mark_session_committed(conn, user_id=user_id, session_id=session_id, updated_at=now)
            return

        current_state_round = self._get_user_skill_call_round(conn, user_id=user_id)
        commit_base_round = max(base_round, current_state_round)
        commit_round = commit_base_round + total_rounds
        updates = conn.execute(
            """
            SELECT skill_name, last_session_skill_call_round, session_lrfu_score
            FROM pending_skill_updates
            WHERE user_id = ? AND session_id = ? AND committed = 0
                  AND last_session_skill_call_round > 0
            """,
            (user_id, session_id),
        ).fetchall()
        for skill_name, last_round, session_score in updates:
            effective_reward = LRFUCache.decayed_score(
                float(session_score),
                last_update_round=int(last_round),
                current_round=total_rounds,
                decay=self.decay,
            )
            row = conn.execute(
                """
                SELECT score, last_update_round
                FROM user_skill_lrfu
                WHERE user_id = ? AND skill_name = ?
                """,
                (user_id, skill_name),
            ).fetchone()
            if row is None:
                new_score = effective_reward
            else:
                new_score = LRFUCache.decayed_score(
                    float(row[0]),
                    last_update_round=int(row[1]),
                    current_round=commit_round,
                    decay=self.decay,
                ) + effective_reward
            conn.execute(
                """
                INSERT INTO user_skill_lrfu (user_id, skill_name, score, last_update_round)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, skill_name) DO UPDATE SET
                    score=excluded.score,
                    last_update_round=excluded.last_update_round
                """,
                (user_id, skill_name, new_score, commit_round),
            )

        conn.execute(
            """
            INSERT INTO user_skill_state (user_id, user_skill_call_round)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                user_skill_call_round=excluded.user_skill_call_round
            """,
            (user_id, commit_round),
        )
        self._mark_session_committed(conn, user_id=user_id, session_id=session_id, updated_at=now)
        self._prune(conn, user_id=user_id)

    def _mark_session_committed(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        session_id: str,
        updated_at: float,
    ) -> None:
        conn.execute(
            """
            UPDATE pending_skill_updates
            SET committed = 1, updated_at = ?
            WHERE user_id = ? AND session_id = ?
            """,
            (updated_at, user_id, session_id),
        )
        conn.execute(
            """
            UPDATE pending_skill_sessions
            SET committed = 1, updated_at = ?
            WHERE user_id = ? AND session_id = ?
            """,
            (updated_at, user_id, session_id),
        )

    def _prune(self, conn: sqlite3.Connection, *, user_id: str) -> None:
        rows = conn.execute(
            """
            SELECT skill_name
            FROM user_skill_lrfu
            WHERE user_id = ?
            ORDER BY score DESC, last_update_round DESC, skill_name
            LIMIT -1 OFFSET ?
            """,
            (user_id, self.max_entries),
        ).fetchall()
        if not rows:
            return
        conn.executemany(
            "DELETE FROM user_skill_lrfu WHERE user_id = ? AND skill_name = ?",
            [(user_id, str(row[0])) for row in rows],
        )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _get_user_skill_call_round(self, conn: sqlite3.Connection, *, user_id: str) -> int:
        row = conn.execute(
            "SELECT user_skill_call_round FROM user_skill_state WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO user_skill_state (user_id, user_skill_call_round) VALUES (?, 0)",
                (user_id,),
            )
            return 0
        return int(row[0])

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_skill_lrfu (
                    user_id TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    score REAL NOT NULL,
                    last_update_round INTEGER NOT NULL,
                    PRIMARY KEY (user_id, skill_name)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_skill_state (
                    user_id TEXT PRIMARY KEY,
                    user_skill_call_round INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_skill_sessions (
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    base_user_skill_call_round INTEGER NOT NULL,
                    session_skill_call_round INTEGER NOT NULL,
                    committed INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (user_id, session_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_skill_updates (
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    last_session_skill_call_round INTEGER NOT NULL,
                    call_count INTEGER NOT NULL,
                    session_lrfu_score REAL NOT NULL,
                    committed INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (user_id, session_id, skill_name)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pending_skill_sessions_user_committed "
                "ON pending_skill_sessions(user_id, committed, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_skill_lrfu_user_score "
                "ON user_skill_lrfu(user_id, score)"
            )
