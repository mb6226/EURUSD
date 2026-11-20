from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

DEFAULT_RESEARCH_LEDGER_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "research" / "continuous_learning.sqlite"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_experiments (
    experiment_id TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    replay_id TEXT NOT NULL,
    source_history_sha256 TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    evaluated_at_utc TEXT NOT NULL,
    replay_id TEXT NOT NULL,
    source_history_sha256 TEXT NOT NULL,
    report_sha256 TEXT NOT NULL,
    report_json TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES research_experiments(experiment_id)
);
CREATE TABLE IF NOT EXISTS research_review_events (
    event_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL,
    review_state TEXT NOT NULL CHECK (review_state IN ('RESEARCH_ONLY', 'REJECTED', 'ELIGIBLE_FOR_HUMAN_REVIEW')),
    rationale TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES research_experiments(experiment_id)
);
CREATE TRIGGER IF NOT EXISTS trg_research_experiments_no_update BEFORE UPDATE ON research_experiments
BEGIN SELECT RAISE(ABORT, 'research experiments are append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_research_experiments_no_delete BEFORE DELETE ON research_experiments
BEGIN SELECT RAISE(ABORT, 'research experiments are append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_research_evaluations_no_update BEFORE UPDATE ON research_evaluations
BEGIN SELECT RAISE(ABORT, 'research evaluations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_research_evaluations_no_delete BEFORE DELETE ON research_evaluations
BEGIN SELECT RAISE(ABORT, 'research evaluations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_research_review_events_no_update BEFORE UPDATE ON research_review_events
BEGIN SELECT RAISE(ABORT, 'research review events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_research_review_events_no_delete BEFORE DELETE ON research_review_events
BEGIN SELECT RAISE(ABORT, 'research review events are append-only'); END;
"""


class ContinuousLearningResearchStore:
    """Explicitly opened append-only ledger for reproducible research artifacts."""

    def __init__(self, db_path: str | Path = DEFAULT_RESEARCH_LEDGER_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path, timeout=30)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(_SCHEMA)

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @staticmethod
    def _canonical(value: Mapping[str, Any]) -> str:
        return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)

    def append_experiment(self, manifest: Mapping[str, Any]) -> str:
        if not isinstance(manifest, Mapping):
            raise TypeError("manifest must be a mapping")
        required = ("experiment_id", "created_at_utc", "replay_id", "source_history_sha256",
                    "code_sha256", "parameter_sha256", "engine_id", "engine_version")
        if any(not manifest.get(k) for k in required):
            raise ValueError("EXPERIMENT_MANIFEST_INCOMPLETE")
        identity_payload = dict(manifest)
        declared_id = identity_payload.pop("experiment_id", None)
        expected_id = sha256(self._canonical(identity_payload).encode("utf-8")).hexdigest()
        if declared_id != expected_id:
            raise ValueError("EXPERIMENT_ID_DOES_NOT_MATCH_MANIFEST")
        canonical = self._canonical(manifest)
        digest = sha256(canonical.encode("utf-8")).hexdigest()
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT OR IGNORE INTO research_experiments
                   (experiment_id, created_at_utc, replay_id, source_history_sha256, manifest_sha256, manifest_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (manifest["experiment_id"], manifest["created_at_utc"], manifest["replay_id"],
                 manifest["source_history_sha256"], digest, canonical),
            )
            row = connection.execute(
                "SELECT manifest_sha256 FROM research_experiments WHERE experiment_id=?",
                (manifest["experiment_id"],),
            ).fetchone()
            if row is None or row["manifest_sha256"] != digest:
                raise ValueError("EXPERIMENT_ID_COLLISION_OR_MANIFEST_MISMATCH")
            connection.commit()
        return digest

    def append_evaluation(self, *, experiment_id: str, replay_id: str,
                          source_history_sha256: str, evaluated_at_utc: str,
                          report: Mapping[str, Any]) -> str:
        if not isinstance(report, Mapping):
            raise TypeError("report must be a mapping")
        if report.get("replay_id") != replay_id or report.get("source_history_sha256") != source_history_sha256:
            raise ValueError("EVALUATION_REPORT_REPLAY_OR_SOURCE_MISMATCH")
        try:
            timestamp = datetime.fromisoformat(evaluated_at_utc.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            raise ValueError("evaluated_at_utc must be ISO-8601")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("evaluated_at_utc must be timezone-aware")
        canonical = self._canonical(report)
        report_hash = sha256(canonical.encode("utf-8")).hexdigest()
        evaluation_id = sha256(f"{experiment_id}|{replay_id}|{source_history_sha256}|{report_hash}".encode()).hexdigest()
        with closing(self._connect()) as connection:
            experiment = connection.execute(
                "SELECT replay_id, source_history_sha256 FROM research_experiments WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
            if experiment is None:
                raise ValueError("EXPERIMENT_NOT_REGISTERED")
            if experiment["replay_id"] != replay_id or experiment["source_history_sha256"] != source_history_sha256:
                raise ValueError("EVALUATION_REPLAY_OR_SOURCE_MISMATCH")
            connection.execute(
                """INSERT OR IGNORE INTO research_evaluations
                   (evaluation_id, experiment_id, evaluated_at_utc, replay_id, source_history_sha256, report_sha256, report_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (evaluation_id, experiment_id, timestamp.astimezone(timezone.utc).isoformat(),
                 replay_id, source_history_sha256, report_hash, canonical),
            )
            connection.commit()
        return evaluation_id

    def append_review_event(self, *, experiment_id: str, occurred_at_utc: str,
                            review_state: str, rationale: str) -> str:
        if review_state not in {"RESEARCH_ONLY", "REJECTED", "ELIGIBLE_FOR_HUMAN_REVIEW"}:
            raise ValueError("UNSUPPORTED_REVIEW_STATE")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("REVIEW_RATIONALE_REQUIRED")
        try:
            timestamp = datetime.fromisoformat(occurred_at_utc.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            raise ValueError("occurred_at_utc must be ISO-8601")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("occurred_at_utc must be timezone-aware")
        event_id = sha256(f"{experiment_id}|{timestamp.isoformat()}|{review_state}|{rationale}".encode()).hexdigest()
        with closing(self._connect()) as connection:
            exists = connection.execute("SELECT 1 FROM research_experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
            if exists is None:
                raise ValueError("EXPERIMENT_NOT_REGISTERED")
            connection.execute(
                """INSERT OR IGNORE INTO research_review_events
                   (event_id, experiment_id, occurred_at_utc, review_state, rationale)
                   VALUES (?, ?, ?, ?, ?)""",
                (event_id, experiment_id, timestamp.astimezone(timezone.utc).isoformat(), review_state, rationale.strip()),
            )
            connection.commit()
        return event_id

    def integrity_check(self) -> str:
        with closing(self._connect()) as connection:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
