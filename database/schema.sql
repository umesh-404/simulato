-- Simulato database schema
-- SQLite3
-- Canonical Law 7: question records are immutable once stored.
-- Modifications create new version records.

CREATE TABLE IF NOT EXISTS tests (
    test_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    test_name       TEXT    NOT NULL UNIQUE,
    created_at      TEXT    NOT NULL,  -- ISO8601 UTC
    question_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS questions (
    question_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id          INTEGER NOT NULL,
    canonical_text   TEXT    NOT NULL,
    sha256_hash      TEXT    NOT NULL,
    simhash          TEXT,
    embedding_vector BLOB,
    option_a         TEXT    NOT NULL,
    option_b         TEXT    NOT NULL,
    option_c         TEXT    NOT NULL,
    option_d         TEXT    NOT NULL,
    correct_answer   TEXT    NOT NULL,  -- The actual answer TEXT, not letter
    answer_letter    TEXT,              -- Letter (A/B/C/D) for reference only
    version          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT    NOT NULL,  -- ISO8601 UTC
    FOREIGN KEY (test_id) REFERENCES tests(test_id)
);

CREATE TABLE IF NOT EXISTS question_snapshots (
    snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id     INTEGER NOT NULL,
    run_id          TEXT    NOT NULL,
    screenshot_path TEXT,
    ai_response     TEXT,              -- Full JSON from Grok
    selected_answer TEXT    NOT NULL,  -- The answer text that was selected
    decision_source TEXT    NOT NULL,  -- 'database', 'ai', 'operator'
    created_at      TEXT    NOT NULL,  -- ISO8601 UTC
    FOREIGN KEY (question_id) REFERENCES questions(question_id)
);

CREATE INDEX IF NOT EXISTS idx_questions_test_id ON questions(test_id);
CREATE INDEX IF NOT EXISTS idx_questions_sha256 ON questions(sha256_hash);
CREATE INDEX IF NOT EXISTS idx_questions_test_hash ON questions(test_id, sha256_hash);
CREATE INDEX IF NOT EXISTS idx_snapshots_question ON question_snapshots(question_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_run ON question_snapshots(run_id);
