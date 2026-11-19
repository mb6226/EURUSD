from __future__ import annotations

from contextlib import closing
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from eurusd_ai_monitor.storage.market_data_store import Candle, TIMEFRAME_SECONDS

_SESSIONS = {
    "LONDON": (ZoneInfo("Europe/London"), time(12, 0)),
    "NEW_YORK": (ZoneInfo("America/New_York"), time(12, 0)),
}


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _decimal(value: Decimal, name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be a positive finite Decimal")
    return value


def _candle_id(candle: Candle) -> str:
    stamp = candle.candle_open_time_utc.isoformat().replace("+00:00", "Z")
    return f"{candle.broker_server}|{candle.symbol}|{candle.timeframe}|{stamp}"


class ObservationStore:
    """Durable research observations; no position, order, or P/L records."""

    def __init__(self, database_path: str | Path) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS setup_observations (
                    setup_key TEXT PRIMARY KEY,
                    broker_server TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    session_name TEXT NOT NULL CHECK(session_name IN ('LONDON','NEW_YORK')),
                    session_date TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK(direction IN ('UP','DOWN')),
                    reference_at_utc TEXT NOT NULL,
                    reference_price TEXT NOT NULL,
                    pip_size TEXT NOT NULL,
                    session_end_utc TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ACTIVE','COMPLETED','DATA_CONFLICT')),
                    mfe_pips TEXT NOT NULL DEFAULT '0',
                    mae_pips TEXT NOT NULL DEFAULT '0',
                    mfe_at_utc TEXT,
                    mae_at_utc TEXT,
                    last_candle_open_utc TEXT,
                    candles_processed INTEGER NOT NULL DEFAULT 0,
                    started_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT,
                    conflict_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS observation_candles (
                    setup_key TEXT NOT NULL,
                    candle_open_utc TEXT NOT NULL,
                    open_price TEXT NOT NULL,
                    high_price TEXT NOT NULL,
                    low_price TEXT NOT NULL,
                    close_price TEXT NOT NULL,
                    PRIMARY KEY(setup_key, candle_open_utc),
                    FOREIGN KEY(setup_key) REFERENCES setup_observations(setup_key)
                        ON DELETE RESTRICT
                );
                CREATE TRIGGER IF NOT EXISTS trg_observation_candles_no_update
                BEFORE UPDATE ON observation_candles BEGIN
                    SELECT RAISE(ABORT, 'observation candle evidence is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_observation_candles_no_delete
                BEFORE DELETE ON observation_candles BEGIN
                    SELECT RAISE(ABORT, 'observation candle evidence is immutable');
                END;
            """)

    def _connect(self):
        db = sqlite3.connect(self._path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=20000")
        return db

    def update(
        self, *, setup_key: str, broker_server: str, symbol: str,
        session_name: str | None, session_date: str | None,
        direction: str, reference_at_utc: datetime, reference_price: Decimal,
        pip_size: Decimal, evaluated_at_utc: datetime, candles: tuple[Candle, ...],
        eligible: bool,
    ) -> dict:
        reference_at = _utc(reference_at_utc, "reference_at_utc")
        evaluated = _utc(evaluated_at_utc, "evaluated_at_utc")
        reference = _decimal(reference_price, "reference_price")
        pip = _decimal(pip_size, "pip_size")
        if direction not in ("UP", "DOWN"):
            raise ValueError("direction must be UP or DOWN")
        if not isinstance(candles, tuple) or any(not isinstance(c, Candle) for c in candles):
            raise TypeError("candles must be a tuple of Candle values")
        if tuple(sorted(candles, key=lambda c: c.candle_open_time_utc)) != candles:
            raise ValueError("candles must be chronological")

        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT * FROM setup_observations WHERE setup_key=?", (setup_key,)
                ).fetchone()
                if row is None:
                    if not eligible:
                        db.commit()
                        return self._waiting(setup_key)
                    if session_name not in _SESSIONS or not session_date:
                        raise ValueError("eligible observation requires a known session and date")
                    zone, end_time = _SESSIONS[session_name]
                    local_end = datetime.combine(
                        datetime.fromisoformat(session_date).date(), end_time, tzinfo=zone
                    )
                    end_utc = local_end.astimezone(timezone.utc)
                    if reference_at >= end_utc:
                        db.commit()
                        return self._waiting(setup_key)
                    db.execute("""
                        INSERT INTO setup_observations (
                            setup_key,broker_server,symbol,session_name,session_date,
                            direction,reference_at_utc,reference_price,pip_size,
                            session_end_utc,status,started_at_utc
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        setup_key, broker_server, symbol, session_name, session_date,
                        direction, reference_at.isoformat(), str(reference), str(pip),
                        end_utc.isoformat(), "ACTIVE", evaluated.isoformat(),
                    ))
                    row = db.execute(
                        "SELECT * FROM setup_observations WHERE setup_key=?", (setup_key,)
                    ).fetchone()
                else:
                    immutable = (
                        row["broker_server"] == broker_server
                        and row["symbol"] == symbol
                        and row["direction"] == direction
                        and row["reference_at_utc"] == reference_at.isoformat()
                        and Decimal(row["reference_price"]) == reference
                        and Decimal(row["pip_size"]) == pip
                    )
                    if not immutable:
                        db.execute("""
                            UPDATE setup_observations
                            SET status='DATA_CONFLICT',
                                conflict_reason='SETUP_REFERENCE_METADATA_CHANGED'
                            WHERE setup_key=?
                        """, (setup_key,))
                        db.commit()
                        return self._read(db, setup_key)

                row = db.execute(
                    "SELECT * FROM setup_observations WHERE setup_key=?", (setup_key,)
                ).fetchone()
                if row["status"] != "ACTIVE":
                    db.commit()
                    return self._read(db, setup_key)

                end_utc = datetime.fromisoformat(row["session_end_utc"])
                ref = Decimal(row["reference_price"])
                pip = Decimal(row["pip_size"])
                mfe, mae = Decimal(row["mfe_pips"]), Decimal(row["mae_pips"])
                mfe_at, mae_at = row["mfe_at_utc"], row["mae_at_utc"]
                last = row["last_candle_open_utc"]
                processed = int(row["candles_processed"])

                for candle in candles:
                    if (candle.broker_server != broker_server or candle.symbol != symbol
                            or candle.timeframe != "M1"):
                        continue
                    opened = candle.candle_open_time_utc
                    closed = opened + timedelta(seconds=TIMEFRAME_SECONDS["M1"])
                    if opened < reference_at or opened >= end_utc or closed > evaluated:
                        continue
                    opened_text = opened.isoformat()
                    values = (str(candle.open), str(candle.high), str(candle.low), str(candle.close))
                    existing = db.execute("""
                        SELECT open_price,high_price,low_price,close_price
                        FROM observation_candles WHERE setup_key=? AND candle_open_utc=?
                    """, (setup_key, opened_text)).fetchone()
                    if existing is not None:
                        if tuple(existing) != values:
                            db.execute("""
                                UPDATE setup_observations
                                SET status='DATA_CONFLICT',
                                    conflict_reason='PROCESSED_CANDLE_OHLC_REVISED'
                                WHERE setup_key=?
                            """, (setup_key,))
                            break
                        continue
                    if last is not None and opened_text <= last:
                        continue
                    db.execute("""
                        INSERT INTO observation_candles
                        (setup_key,candle_open_utc,open_price,high_price,low_price,close_price)
                        VALUES (?,?,?,?,?,?)
                    """, (setup_key, opened_text, *values))
                    if direction == "UP":
                        favorable = max(Decimal("0"), (candle.high - ref) / pip)
                        adverse = max(Decimal("0"), (ref - candle.low) / pip)
                    else:
                        favorable = max(Decimal("0"), (ref - candle.low) / pip)
                        adverse = max(Decimal("0"), (candle.high - ref) / pip)
                    if favorable > mfe:
                        mfe, mfe_at = favorable, closed.isoformat()
                    if adverse > mae:
                        mae, mae_at = adverse, closed.isoformat()
                    last = opened_text
                    processed += 1

                current = db.execute(
                    "SELECT status FROM setup_observations WHERE setup_key=?", (setup_key,)
                ).fetchone()["status"]
                completed_at = None
                if current == "ACTIVE" and evaluated >= end_utc:
                    current = "COMPLETED"
                    completed_at = end_utc.isoformat()
                db.execute("""
                    UPDATE setup_observations SET status=?,mfe_pips=?,mae_pips=?,
                        mfe_at_utc=?,mae_at_utc=?,last_candle_open_utc=?,
                        candles_processed=?,completed_at_utc=COALESCE(?,completed_at_utc)
                    WHERE setup_key=?
                """, (
                    current, str(mfe), str(mae), mfe_at, mae_at, last, processed,
                    completed_at, setup_key,
                ))
                db.commit()
                return self._read(db, setup_key)
            except Exception:
                db.rollback()
                raise

    @staticmethod
    def _waiting(setup_key):
        return {
            "status": "WAITING_FOR_SESSION_ELIGIBILITY", "setup_key": setup_key,
            "observation_type": "PRICE_EXCURSION_ONLY",
            "trade_authority": "NONE", "order_execution": "DISABLED",
        }

    @staticmethod
    def _read(db, setup_key):
        row = db.execute(
            "SELECT * FROM setup_observations WHERE setup_key=?", (setup_key,)
        ).fetchone()
        if row is None:
            return ObservationStore._waiting(setup_key)
        return {
            "status": row["status"], "setup_key": row["setup_key"],
            "session": row["session_name"], "session_date": row["session_date"],
            "direction": row["direction"],
            "reference_price": row["reference_price"],
            "reference_at_utc": row["reference_at_utc"],
            "session_end_utc": row["session_end_utc"],
            "mfe_pips": row["mfe_pips"], "mae_pips": row["mae_pips"],
            "mfe_at_utc": row["mfe_at_utc"], "mae_at_utc": row["mae_at_utc"],
            "last_candle_open_utc": row["last_candle_open_utc"],
            "candles_processed": row["candles_processed"],
            "completed_at_utc": row["completed_at_utc"],
            "conflict_reason": row["conflict_reason"],
            "observation_type": "PRICE_EXCURSION_ONLY",
            "reference_type": "RETEST_CANDLE_CLOSE",
            "trade_authority": "NONE", "order_execution": "DISABLED",
        }


class SetupOutcomeTracker:
    """Tracks closed-M1 price excursions from the retest close to session end."""

    def __init__(self, store: ObservationStore, *, pip_size: Decimal) -> None:
        if not isinstance(store, ObservationStore):
            raise TypeError("store must be an ObservationStore")
        self._store = store
        self._pip_size = _decimal(pip_size, "pip_size")

    def assess(
        self, *, evaluated_at_utc: datetime, broker_server: str, symbol: str,
        lifecycle_id: str | None, setup_assessment: dict,
        session_eligibility: dict, m1_candles: tuple[Candle, ...],
    ) -> dict:
        evaluated = _utc(evaluated_at_utc, "evaluated_at_utc")
        if not isinstance(setup_assessment, dict) or not isinstance(session_eligibility, dict):
            raise TypeError("setup_assessment and session_eligibility must be dictionaries")
        pullback = setup_assessment.get("pullback")
        if setup_assessment.get("stage") != "PATTERN_CONFIRMED" or not isinstance(pullback, dict):
            return {
                "status": "WAIT_SETUP", "reason_code": "PATTERN_NOT_CONFIRMED",
                "observation_type": "PRICE_EXCURSION_ONLY",
                "trade_authority": "NONE", "order_execution": "DISABLED",
            }
        retest_id = pullback.get("retest_candle_id")
        if not lifecycle_id or not retest_id:
            return {
                "status": "BLOCKED", "reason_code": "SETUP_IDENTITY_INCOMPLETE",
                "trade_authority": "NONE", "order_execution": "DISABLED",
            }
        setup_key = f"{lifecycle_id}:{retest_id}"
        retest = next((c for c in m1_candles if c.timeframe == "M1" and _candle_id(c) == retest_id), None)
        if retest is None:
            return {
                "status": "BLOCKED", "setup_key": setup_key,
                "reason_code": "RETEST_CANDLE_NOT_IN_CURRENT_EVIDENCE",
                "trade_authority": "NONE", "order_execution": "DISABLED",
            }
        direction = setup_assessment.get("trend_direction")
        if direction not in ("UP", "DOWN"):
            return {"status": "BLOCKED", "setup_key": setup_key,
                    "reason_code": "DIRECTION_UNAVAILABLE",
                    "trade_authority": "NONE", "order_execution": "DISABLED"}
        reference_at = datetime.fromisoformat(pullback["confirmed_at_utc"].replace("Z", "+00:00"))
        eligible = session_eligibility.get("status") == "RESEARCH_ELIGIBLE"
        result = self._store.update(
            setup_key=setup_key, broker_server=broker_server, symbol=symbol,
            session_name=session_eligibility.get("session"),
            session_date=session_eligibility.get("session_date"),
            direction=direction, reference_at_utc=reference_at,
            reference_price=retest.close, pip_size=self._pip_size,
            evaluated_at_utc=evaluated, candles=m1_candles, eligible=eligible,
        )
        result.update({
            "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE",
            "order_execution": "DISABLED",
        })
        return result
