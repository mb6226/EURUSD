from __future__ import annotations
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

_LONDON = ZoneInfo("Europe/London")
_NEW_YORK = ZoneInfo("America/New_York")
_SESSION_WINDOWS = (
    ("LONDON", _LONDON, time(8, 0), time(12, 0)),
    ("NEW_YORK", _NEW_YORK, time(8, 0), time(12, 0)),
)

@dataclass(frozen=True)
class SessionReservation:
    broker_server: str
    symbol: str
    session_name: str
    session_date: str
    risk_date: str
    setup_key: str
    risk_pips: Decimal
    stop_loss_pips: Decimal
    take_profit_pips: Decimal
    created_at_utc: datetime

class SessionRiskStore:
    """Durable, transactional one-setup-per-session reservation ledger."""
    def __init__(self, database_path: str | Path) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS session_setup_reservations (
                    broker_server TEXT NOT NULL, symbol TEXT NOT NULL,
                    session_name TEXT NOT NULL CHECK (session_name IN ('LONDON','NEW_YORK')),
                    session_date TEXT NOT NULL, risk_date TEXT NOT NULL,
                    setup_key TEXT NOT NULL, risk_pips TEXT NOT NULL,
                    stop_loss_pips TEXT NOT NULL, take_profit_pips TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    PRIMARY KEY (broker_server, symbol, session_name, session_date),
                    UNIQUE (broker_server, symbol, setup_key)
                )
            """)
            db.execute("""CREATE INDEX IF NOT EXISTS idx_session_risk_day
                ON session_setup_reservations (broker_server, symbol, risk_date)""")

    def _connect(self):
        db = sqlite3.connect(self._path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _from_row(row):
        return SessionReservation(
            row["broker_server"], row["symbol"], row["session_name"],
            row["session_date"], row["risk_date"], row["setup_key"],
            Decimal(row["risk_pips"]), Decimal(row["stop_loss_pips"]),
            Decimal(row["take_profit_pips"]), datetime.fromisoformat(row["created_at_utc"]),
        )

    def reserve(self, *, broker_server, symbol, session_name, session_date,
                risk_date, setup_key, risk_pips, stop_loss_pips,
                take_profit_pips, max_daily_risk_pips, created_at_utc):
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                existing = db.execute("""SELECT * FROM session_setup_reservations
                    WHERE broker_server=? AND symbol=? AND setup_key=?""",
                    (broker_server, symbol, setup_key)).fetchone()
                if existing is not None:
                    reservation = self._from_row(existing)
                    total = self._daily_total(db, broker_server, symbol, reservation.risk_date)
                    db.commit()
                    return "ALREADY_RESERVED", reservation, total
                existing = db.execute("""SELECT * FROM session_setup_reservations
                    WHERE broker_server=? AND symbol=? AND session_name=? AND session_date=?""",
                    (broker_server, symbol, session_name, session_date)).fetchone()
                if existing is not None:
                    total = self._daily_total(db, broker_server, symbol, risk_date)
                    db.commit()
                    return "SESSION_SLOT_USED", self._from_row(existing), total
                total = self._daily_total(db, broker_server, symbol, risk_date)
                proposed = total + risk_pips
                if proposed > max_daily_risk_pips:
                    db.commit()
                    return "DAILY_RISK_LIMIT", None, total
                db.execute("""INSERT INTO session_setup_reservations
                    (broker_server,symbol,session_name,session_date,risk_date,setup_key,
                     risk_pips,stop_loss_pips,take_profit_pips,created_at_utc)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (broker_server, symbol, session_name, session_date, risk_date,
                     setup_key, str(risk_pips), str(stop_loss_pips), str(take_profit_pips),
                     created_at_utc.astimezone(timezone.utc).isoformat()))
                row = db.execute("""SELECT * FROM session_setup_reservations
                    WHERE broker_server=? AND symbol=? AND setup_key=?""",
                    (broker_server, symbol, setup_key)).fetchone()
                db.commit()
                return "RESERVED", self._from_row(row), proposed
            except Exception:
                db.rollback()
                raise

    @staticmethod
    def _daily_total(db, broker_server, symbol, risk_date):
        rows = db.execute("""SELECT risk_pips FROM session_setup_reservations
            WHERE broker_server=? AND symbol=? AND risk_date=?""",
            (broker_server, symbol, risk_date)).fetchall()
        return sum((Decimal(row["risk_pips"]) for row in rows), Decimal("0"))

class SessionEligibilityRiskGate:
    """Assessment-only session and risk gate; never creates or sends orders."""
    def __init__(self, store, *, stop_loss_pips, take_profit_pips, max_daily_risk_pips):
        if not isinstance(store, SessionRiskStore):
            raise TypeError("store must be a SessionRiskStore")
        for name, value in (("stop_loss_pips", stop_loss_pips),
                            ("take_profit_pips", take_profit_pips),
                            ("max_daily_risk_pips", max_daily_risk_pips)):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be a positive finite Decimal")
        if take_profit_pips <= stop_loss_pips:
            raise ValueError("take_profit_pips must exceed stop_loss_pips")
        if max_daily_risk_pips < stop_loss_pips:
            raise ValueError("daily risk budget must cover at least one stop loss")
        self._store, self._stop_loss = store, stop_loss_pips
        self._take_profit, self._daily_limit = take_profit_pips, max_daily_risk_pips

    def assess(self, *, evaluated_at_utc, broker_server, symbol, setup_assessment, lifecycle_id):
        evaluated = self._utc(evaluated_at_utc)
        if not isinstance(broker_server, str) or not broker_server.strip():
            raise ValueError("broker_server must be non-empty")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be non-empty")
        if not isinstance(setup_assessment, dict):
            raise TypeError("setup_assessment must be a dictionary")
        session = self._active_session(evaluated)
        if session is None:
            return self._result("OUTSIDE_SESSION", ("OUTSIDE_LONDON_AND_NEW_YORK_WINDOWS",),
                                evaluated, None, None, Decimal("0"))
        if setup_assessment.get("stage") != "PATTERN_CONFIRMED":
            return self._result("WAIT_SETUP", ("SETUP_PATTERN_NOT_CONFIRMED",),
                                evaluated, session[0], None, Decimal("0"))
        pullback = setup_assessment.get("pullback")
        retest_id = pullback.get("retest_candle_id") if isinstance(pullback, dict) else None
        if not lifecycle_id or not retest_id:
            return self._result("BLOCKED", ("SETUP_IDENTITY_INCOMPLETE",),
                                evaluated, session[0], None, Decimal("0"))
        name, zone, _, _ = session
        session_date = evaluated.astimezone(zone).date().isoformat()
        risk_date = evaluated.astimezone(_LONDON).date().isoformat()
        key = f"{lifecycle_id}:{retest_id}"
        status, reservation, total = self._store.reserve(
            broker_server=broker_server, symbol=symbol, session_name=name,
            session_date=session_date, risk_date=risk_date, setup_key=key,
            risk_pips=self._stop_loss, stop_loss_pips=self._stop_loss,
            take_profit_pips=self._take_profit, max_daily_risk_pips=self._daily_limit,
            created_at_utc=evaluated)
        if status in ("RESERVED", "ALREADY_RESERVED"):
            return self._result("RESEARCH_ELIGIBLE", ("SESSION_AND_RISK_GATES_PASSED",),
                                evaluated, name, reservation, total)
        if status == "SESSION_SLOT_USED":
            return self._result("BLOCKED", ("ONE_SETUP_PER_SESSION_LIMIT_REACHED",),
                                evaluated, name, reservation, total)
        return self._result("BLOCKED", ("DAILY_RISK_BUDGET_EXCEEDED",),
                            evaluated, name, None, total)

    @staticmethod
    def _active_session(evaluated):
        for name, zone, start, end in _SESSION_WINDOWS:
            local = evaluated.astimezone(zone)
            if start <= local.time().replace(tzinfo=None) < end:
                return name, zone, start, end
        return None

    def _result(self, status, reasons, evaluated, session_name, reservation, daily_total):
        return {
            "status": status, "session": session_name,
            "evaluated_at_utc": evaluated.isoformat(),
            "session_date": reservation.session_date if reservation else None,
            "risk_date": reservation.risk_date if reservation else (
                evaluated.astimezone(_LONDON).date().isoformat() if session_name else None),
            "setup_key": reservation.setup_key if reservation else None,
            "stop_loss_pips": str(self._stop_loss),
            "take_profit_pips": str(self._take_profit),
            "trailing_stop_enabled": False,
            "daily_risk_used_pips": str(daily_total),
            "daily_risk_limit_pips": str(self._daily_limit),
            "remaining_daily_risk_pips": str(max(Decimal("0"), self._daily_limit-daily_total)),
            "reason_codes": list(reasons), "decision_authority": "ASSESSMENT_ONLY",
            "trade_authority": "NONE", "order_execution": "DISABLED",
        }

    @staticmethod
    def _utc(value):
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at_utc must be timezone-aware")
        return value.astimezone(timezone.utc)
