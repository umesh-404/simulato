"""
Simulato database manager.

Provides all database operations for tests and questions.
Uses SQLite3. Enforces dataset immutability (Canonical Law 7):
    - Stored questions are never modified in place.
    - Changes create new version records.

All public methods log their actions (Canonical Law 11).
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from controller.config import DATABASE_PATH, DATABASE_DIR, DATASETS_DIR
from controller.utils.logger import get_logger

logger = get_logger("db_manager")

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class DatabaseManager:
    """
    Thread-safe (single-writer) SQLite database manager.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or DATABASE_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._initialize()

    def _initialize(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        self._conn.executescript(schema_sql)
        self._conn.commit()
        logger.info("Database initialized at %s", self._db_path)

        # Apply any required schema migrations for existing databases.
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """
        Apply lightweight, in-place schema migrations.

        This keeps behavior deterministic while allowing us to evolve
        the database without destructive changes.
        """
        # 1) Ensure question_snapshots.image_phash column exists
        cursor = self._conn.execute("PRAGMA table_info(question_snapshots)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "image_phash" not in columns:
            logger.info("Migrating DB: adding image_phash column to question_snapshots")
            self._conn.execute(
                "ALTER TABLE question_snapshots ADD COLUMN image_phash TEXT"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshots_phash ON question_snapshots(image_phash)"
            )
            self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("Database connection closed")

    # ------------------------------------------------------------------
    # Test operations
    # ------------------------------------------------------------------

    def create_test(self, test_name: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            "INSERT INTO tests (test_name, created_at, question_count) VALUES (?, ?, 0)",
            (test_name, now),
        )
        self._conn.commit()
        test_id = cursor.lastrowid
        logger.info("Created test: name=%s, id=%d", test_name, test_id)
        return test_id

    def get_test_by_name(self, test_name: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM tests WHERE test_name = ?", (test_name,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_or_create_test(self, test_name: str) -> dict:
        existing = self.get_test_by_name(test_name)
        if existing:
            logger.info("Loaded existing test: %s (id=%d)", test_name, existing["test_id"])
            return existing
        test_id = self.create_test(test_name)
        return self.get_test_by_name(test_name)

    # ------------------------------------------------------------------
    # Question storage (immutable — Canonical Law 7)
    # ------------------------------------------------------------------

    def store_question(
        self,
        test_id: int,
        canonical_text: str,
        sha256_hash: str,
        simhash: str,
        embedding_vector: Optional[bytes],
        option_a: str,
        option_b: str,
        option_c: str,
        option_d: str,
        correct_answer: str,
        answer_letter: str = "",
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()

        existing = self.lookup_by_hash(test_id, sha256_hash)
        version = 1
        if existing:
            version = existing["version"] + 1
            logger.info(
                "Question hash collision — creating version %d (hash=%s)",
                version, sha256_hash[:16],
            )

        cursor = self._conn.execute(
            """INSERT INTO questions
               (test_id, canonical_text, sha256_hash, simhash, embedding_vector,
                option_a, option_b, option_c, option_d,
                correct_answer, answer_letter, version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                test_id, canonical_text, sha256_hash, simhash, embedding_vector,
                option_a, option_b, option_c, option_d,
                correct_answer, answer_letter, version, now,
            ),
        )
        self._conn.execute(
            "UPDATE tests SET question_count = question_count + 1 WHERE test_id = ?",
            (test_id,),
        )
        self._conn.commit()

        question_id = cursor.lastrowid
        logger.info(
            "Stored question: id=%d, test_id=%d, hash=%s, version=%d",
            question_id, test_id, sha256_hash[:16], version,
        )

        self._write_question_json(test_id, question_id, {
            "question_id": question_id,
            "canonical_text": canonical_text,
            "option_a": option_a,
            "option_b": option_b,
            "option_c": option_c,
            "option_d": option_d,
            "correct_answer": correct_answer,
            "answer_letter": answer_letter,
            "version": version,
        })

        return question_id

    def _write_question_json(self, test_id: int, question_id: int, data: dict) -> None:
        test = self._conn.execute(
            "SELECT test_name FROM tests WHERE test_id = ?", (test_id,)
        ).fetchone()
        if not test:
            return
        test_dir = DATASETS_DIR / "tests" / test["test_name"] / "questions"
        test_dir.mkdir(parents=True, exist_ok=True)
        json_path = test_dir / f"question_{question_id:04d}.json"
        json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.debug("Wrote question JSON: %s", json_path)

    # ------------------------------------------------------------------
    # Question lookup (staged — Architecture Spec Section 8)
    # ------------------------------------------------------------------

    def lookup_by_hash(self, test_id: int, sha256_hash: str) -> Optional[dict]:
        row = self._conn.execute(
            """SELECT * FROM questions
               WHERE test_id = ? AND sha256_hash = ?
               ORDER BY version DESC LIMIT 1""",
            (test_id, sha256_hash),
        ).fetchone()
        if row:
            logger.debug("Hash match found: question_id=%d", row["question_id"])
            return dict(row)
        return None

    def lookup_by_simhash(self, test_id: int, simhash: str, max_distance: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM questions WHERE test_id = ? AND simhash IS NOT NULL",
            (test_id,),
        ).fetchall()
        from controller.question_engine.hash_engine import simhash_distance
        matches = []
        for row in rows:
            dist = simhash_distance(simhash, row["simhash"])
            if dist <= max_distance:
                entry = dict(row)
                entry["_simhash_distance"] = dist
                matches.append(entry)
        matches.sort(key=lambda m: m["_simhash_distance"])
        if matches:
            logger.debug("SimHash matches found: %d (best distance=%d)", len(matches), matches[0]["_simhash_distance"])
        return matches

    def get_all_questions_for_test(self, test_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM questions WHERE test_id = ? ORDER BY question_id",
            (test_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Snapshot storage (Canonical Law 10)
    # ------------------------------------------------------------------

    def store_snapshot(
        self,
        question_id: int,
        run_id: str,
        screenshot_path: str,
        ai_response: str,
        selected_answer: str,
        decision_source: str,
        image_phash: str | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """INSERT INTO question_snapshots
               (question_id, run_id, screenshot_path, ai_response,
                selected_answer, decision_source, image_phash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (question_id, run_id, screenshot_path, ai_response, selected_answer, decision_source, image_phash, now),
        )
        self._conn.commit()
        snapshot_id = cursor.lastrowid
        logger.info(
            "Stored snapshot: id=%d, question_id=%d, source=%s",
            snapshot_id, question_id, decision_source,
        )
        return snapshot_id

    # ------------------------------------------------------------------
    # Image-hash lookup (DB-first without AI call)
    # ------------------------------------------------------------------

    def lookup_by_image_phash(self, test_id: int, image_phash: str) -> Optional[dict]:
        """
        Find the most recent question for a given test that has a snapshot
        with the specified image perceptual hash.

        This enables DB-first answering without calling Grok/Gemini when
        the exact same stitched question image has been seen before.
        """
        row = self._conn.execute(
            """
            SELECT q.*
            FROM questions q
            JOIN question_snapshots s ON s.question_id = q.question_id
            WHERE q.test_id = ? AND s.image_phash = ?
            ORDER BY s.created_at DESC
            LIMIT 1
            """,
            (test_id, image_phash),
        ).fetchone()
        if row:
            logger.debug(
                "Image hash match found: question_id=%d, phash=%s",
                row["question_id"], image_phash,
            )
            return dict(row)
        return None
