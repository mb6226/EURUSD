from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

DEFAULT_FORECAST_REPLAY_DB_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "research" / "forecast_replay.sqlite"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS replay_runs (
    replay_id TEXT PRIMARY KEY,
    engine_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    broker_server TEXT NOT NULL,
    start_utc TEXT NOT NULL,
    end_utc TEXT NOT NULL,
    evaluation_cutoff_utc TEXT NOT NULL,
    forecast_cutoff_count INTEGER NOT NULL,
    forecast_record_count INTEGER NOT NULL,
    outcome_available_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS replay_forecasts (
    forecast_id TEXT NOT NULL,
    replay_id TEXT NOT NULL,
    forecast_cutoff_utc TEXT NOT NULL,
    horizon TEXT NOT NULL,
    forecast_direction TEXT NOT NULL,
    expected_move_pips REAL NOT NULL,
    anchor_open_time_utc TEXT NOT NULL,
    anchor_close_price REAL NOT NULL,
    anchor_version_id TEXT NOT NULL,
    target_open_time_utc TEXT NOT NULL,
    target_close_time_utc TEXT NOT NULL,
    target_close_price REAL,
    target_version_id TEXT,
    actual_move_pips REAL,
    outcome_direction TEXT,
    direction_hit INTEGER,
    absolute_error_pips REAL,
    signed_error_pips REAL,
    snapshot_sha256 TEXT NOT NULL,
    forecast_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (replay_id, forecast_id),
    FOREIGN KEY (replay_id) REFERENCES replay_runs(replay_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_replay_forecasts_id ON replay_forecasts(forecast_id);
CREATE INDEX IF NOT EXISTS idx_replay_forecasts_horizon_cutoff
    ON replay_forecasts(horizon, forecast_cutoff_utc);
CREATE TRIGGER IF NOT EXISTS trg_replay_runs_no_update
BEFORE UPDATE ON replay_runs BEGIN SELECT RAISE(ABORT, 'replay_runs is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_replay_runs_no_delete
BEFORE DELETE ON replay_runs BEGIN SELECT RAISE(ABORT, 'replay_runs is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_replay_forecasts_no_update
BEFORE UPDATE ON replay_forecasts BEGIN SELECT RAISE(ABORT, 'replay_forecasts is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_replay_forecasts_no_delete
BEFORE DELETE ON replay_forecasts BEGIN SELECT RAISE(ABORT, 'replay_forecasts is append-only'); END;
"""


class ForecastReplayLedger:
    """Dedicated append-only research ledger; never writes to the market archive."""

    def __init__(self, db_path: str | Path = DEFAULT_FORECAST_REPLAY_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(_SCHEMA)

    def append_run(self, replay: Mapping[str, Any]) -> dict[str, int]:
        if not isinstance(replay, Mapping):
            raise TypeError("replay must be a mapping")
        if replay.get("status") != "COMPLETE" or not replay.get("replay_id"):
            raise ValueError("only completed replay runs can be persisted")
        records = replay.get("records")
        if not isinstance(records, list):
            raise ValueError("replay records must be a list")
        created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        metadata = {
            k: v for k, v in replay.items()
            if k not in {"records", "replay_id", "report_type"}
        }
        inserted = 0
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM replay_runs WHERE replay_id=?", (replay["replay_id"],)
            ).fetchone()
            if exists:
                connection.rollback()
                return {"runs_inserted": 0, "forecasts_inserted": 0, "duplicates_ignored": len(records)}
            connection.execute(
                """INSERT INTO replay_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    replay["replay_id"], replay["engine_version"], replay["symbol"],
                    replay["broker_server"], replay["start_utc"], replay["end_utc"],
                    replay["evaluation_cutoff_utc"], int(replay["forecast_cutoff_count"]),
                    int(replay["forecast_record_count"]), int(replay["outcome_available_count"]),
                    replay["status"], json.dumps(metadata, sort_keys=True, separators=(",", ":"), default=str),
                    created,
                ),
            )
            for row in records:
                connection.execute(
                    """INSERT INTO replay_forecasts (
                        forecast_id,replay_id,forecast_cutoff_utc,horizon,forecast_direction,
                        expected_move_pips,anchor_open_time_utc,anchor_close_price,anchor_version_id,
                        target_open_time_utc,target_close_time_utc,target_close_price,target_version_id,
                        actual_move_pips,outcome_direction,direction_hit,absolute_error_pips,
                        signed_error_pips,snapshot_sha256,forecast_json,created_at_utc
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row["forecast_id"], replay["replay_id"], row["forecast_cutoff_utc"],
                        row["horizon"], row["forecast_direction"], row["expected_move_pips"],
                        row["anchor_open_time_utc"], row["anchor_close_price"], row["anchor_version_id"],
                        row["target_open_time_utc"], row["target_close_time_utc"],
                        row["target_close_price"], row["target_version_id"], row["actual_move_pips"],
                        row["outcome_direction"], None if row["direction_hit"] is None else int(row["direction_hit"]),
                        row["absolute_error_pips"], row["signed_error_pips"], row["snapshot_sha256"],
                        json.dumps(row["forecast_json"], sort_keys=True, separators=(",", ":"), default=str),
                        created,
                    ),
                )
                inserted += 1
            connection.commit()
        return {"runs_inserted": 1, "forecasts_inserted": inserted, "duplicates_ignored": 0}

    @classmethod
    def load_run(
        cls, replay_id: str,
        db_path: str | Path = DEFAULT_FORECAST_REPLAY_DB_PATH,
    ) -> dict[str, Any] | None:
        """Load a complete replay and its full forecast rows without creating or mutating the ledger."""
        path = Path(db_path)
        if not path.is_file():
            return None
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
            connection.row_factory = sqlite3.Row
            run = connection.execute(
                "SELECT * FROM replay_runs WHERE replay_id=?", (replay_id,)
            ).fetchone()
            if run is None:
                return None
            metadata = json.loads(run["metadata_json"])
            rows = connection.execute(
                "SELECT * FROM replay_forecasts WHERE replay_id=? "
                "ORDER BY forecast_cutoff_utc, horizon, forecast_id",
                (replay_id,),
            ).fetchall()
        records = []
        for row in rows:
            records.append({
                "forecast_id": row["forecast_id"],
                "replay_id": row["replay_id"],
                "forecast_cutoff_utc": row["forecast_cutoff_utc"],
                "horizon": row["horizon"],
                "forecast_status": "AVAILABLE",
                "forecast_direction": row["forecast_direction"],
                "expected_move_pips": row["expected_move_pips"],
                "anchor_open_time_utc": row["anchor_open_time_utc"],
                "anchor_close_price": row["anchor_close_price"],
                "anchor_version_id": row["anchor_version_id"],
                "target_open_time_utc": row["target_open_time_utc"],
                "target_close_time_utc": row["target_close_time_utc"],
                "target_close_price": row["target_close_price"],
                "target_version_id": row["target_version_id"],
                "actual_move_pips": row["actual_move_pips"],
                "outcome_direction": row["outcome_direction"],
                "direction_hit": None if row["direction_hit"] is None else bool(row["direction_hit"]),
                "absolute_error_pips": row["absolute_error_pips"],
                "signed_error_pips": row["signed_error_pips"],
                "snapshot_sha256": row["snapshot_sha256"],
                "registry_sha256": None,
                "scenario_context": "NOT_SUPPLIED_FOR_HISTORICAL_CUTOFF",
                "forecast_json": json.loads(row["forecast_json"]),
            })
        return {
            **metadata,
            "report_type": "EURUSD_POINT_IN_TIME_FORECAST_REPLAY",
            "engine_version": run["engine_version"],
            "phase": 45,
            "status": run["status"],
            "replay_id": run["replay_id"],
            "symbol": run["symbol"],
            "broker_server": run["broker_server"],
            "start_utc": run["start_utc"],
            "end_utc": run["end_utc"],
            "evaluation_cutoff_utc": run["evaluation_cutoff_utc"],
            "forecast_cutoff_count": int(run["forecast_cutoff_count"]),
            "forecast_record_count": int(run["forecast_record_count"]),
            "outcome_available_count": int(run["outcome_available_count"]),
            "records": records,
        }

    def get_summary(self) -> dict[str, Any]:
        with closing(sqlite3.connect(f"file:{self.db_path.resolve()}?mode=ro", uri=True)) as connection:
            runs = connection.execute("SELECT COUNT(*) FROM replay_runs").fetchone()[0]
            forecasts = connection.execute("SELECT COUNT(*) FROM replay_forecasts").fetchone()[0]
            outcomes = connection.execute(
                "SELECT COUNT(*) FROM replay_forecasts WHERE actual_move_pips IS NOT NULL"
            ).fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {
            "database_path": str(self.db_path), "run_count": runs,
            "forecast_count": forecasts, "outcome_count": outcomes,
            "integrity_check": integrity, "append_only": True,
        }
