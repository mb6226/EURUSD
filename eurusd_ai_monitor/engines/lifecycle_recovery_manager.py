from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from eurusd_ai_monitor.engines.price_action_runtime import RecoveryStatus
from eurusd_ai_monitor.engines.technical_engine import (
    MARKET_STRUCTURE_ALGORITHM_VERSION,
    _strategy_parameter_version,
)
from eurusd_ai_monitor.models.correction_lifecycle import CorrectionLifecycle
from eurusd_ai_monitor.storage.lifecycle_store import (
    LifecycleIntegrityError,
    LifecycleStore,
)
from eurusd_ai_monitor.storage.market_data_store import MarketDataStore
from eurusd_ai_monitor.strategy_config import StrategyConfig


class LifecycleRecoveryManager:
    """Fail-closed startup recovery gate for one broker/symbol lifecycle stream.

    This manager validates persisted state and provenance. It deliberately does
    not replay revised candles, rewrite lifecycle snapshots, or supersede events.
    Those operations require a separately designed and approved replay workflow.
    """

    def __init__(self, lifecycle_store: LifecycleStore, market_data_store: MarketDataStore):
        if not isinstance(lifecycle_store, LifecycleStore):
            raise TypeError("lifecycle_store must be a LifecycleStore")
        if not isinstance(market_data_store, MarketDataStore):
            raise TypeError("market_data_store must be a MarketDataStore")
        self._lifecycle_store = lifecycle_store
        self._market_data_store = market_data_store

    def recover_stream(
        self,
        broker_server: str,
        symbol: str,
        config: StrategyConfig,
    ) -> RecoveryStatus:
        if not isinstance(config, StrategyConfig):
            raise TypeError("config must be a StrategyConfig")
        status = RecoveryStatus.NORMAL
        reason = "RECOVERY_VALIDATED"
        details: dict[str, Any] = {}
        watermark = 0
        try:
            stream = self._lifecycle_store.load_stream_state(broker_server, symbol)
            watermark = stream.revision_watermark
            audited = self._lifecycle_store.audit_stream(broker_server, symbol)
            details["audited_lifecycles"] = audited
            active = stream.active_record
            if active is not None:
                lifecycle = active.lifecycle
                details["active_lifecycle_id"] = lifecycle.lifecycle_id
                if active.revision_watermark != watermark:
                    status = RecoveryStatus.RECONCILIATION
                    reason = "M5_CANDLE_REVISION_REQUIRES_REPLAY"
                    details.update({
                        "lifecycle_revision_watermark": active.revision_watermark,
                        "current_revision_watermark": watermark,
                    })
                elif (
                    lifecycle.algorithm_version != MARKET_STRUCTURE_ALGORITHM_VERSION
                    or lifecycle.parameter_version != _strategy_parameter_version(config)
                ):
                    status = RecoveryStatus.QUARANTINED
                    reason = "ACTIVE_LIFECYCLE_VERSION_MISMATCH"
                    details.update({
                        "stored_algorithm_version": lifecycle.algorithm_version,
                        "current_algorithm_version": MARKET_STRUCTURE_ALGORITHM_VERSION,
                        "stored_parameter_version": lifecycle.parameter_version,
                        "current_parameter_version": _strategy_parameter_version(config),
                    })
                else:
                    mismatch = self._evidence_mismatch(lifecycle)
                    if mismatch is not None:
                        status = RecoveryStatus.QUARANTINED
                        reason = "ACTIVE_LIFECYCLE_EVIDENCE_MISMATCH"
                        details["evidence_mismatch"] = mismatch
        except Exception as exc:
            status = RecoveryStatus.QUARANTINED
            reason = "LIFECYCLE_INTEGRITY_CHECK_FAILED"
            details["error"] = f"{type(exc).__name__}: {exc}"

        self._lifecycle_store.record_recovery_status(
            broker_server=broker_server,
            symbol=symbol,
            status=status.value,
            reason_code=reason,
            revision_watermark=watermark,
            checked_at_utc=datetime.now(timezone.utc),
            details=details,
        )
        return status

    def mark_reconciliation(
        self, broker_server: str, symbol: str, reason_code: str
    ) -> RecoveryStatus:
        """Persist a runtime-detected revision race as a durable fail-closed gate."""
        watermark = self._lifecycle_store.get_revision_watermark(broker_server, symbol)
        self._lifecycle_store.record_recovery_status(
            broker_server=broker_server,
            symbol=symbol,
            status=RecoveryStatus.RECONCILIATION.value,
            reason_code=reason_code,
            revision_watermark=watermark,
            checked_at_utc=datetime.now(timezone.utc),
            details={"source": "runtime_revision_guard"},
        )
        return RecoveryStatus.RECONCILIATION

    def get_status(self, broker_server: str, symbol: str) -> RecoveryStatus:
        record = self._lifecycle_store.get_recovery_record(broker_server, symbol)
        if record is None:
            return RecoveryStatus.RECONCILIATION
        try:
            return RecoveryStatus(record["status"])
        except (TypeError, ValueError) as exc:
            raise LifecycleIntegrityError("unsupported persisted recovery status") from exc

    def get_details(self, broker_server: str, symbol: str) -> dict[str, Any]:
        record = self._lifecycle_store.get_recovery_record(broker_server, symbol)
        if record is None:
            return {
                "status": RecoveryStatus.RECONCILIATION.value,
                "reason_code": "STARTUP_RECOVERY_NOT_RUN",
                "details": {},
            }
        return {
            "status": record["status"],
            "reason_code": record["reason_code"],
            "revision_watermark": record["revision_watermark"],
            "checked_at_utc": record["checked_at_utc"].isoformat(),
            "details": record["details"],
        }

    def _evidence_mismatch(self, lifecycle: CorrectionLifecycle) -> str | None:
        refs = [
            lifecycle.impulse.start_pivot,
            lifecycle.impulse.end_pivot,
            lifecycle.candidate_start_evidence,
            lifecycle.extreme_evidence,
            *lifecycle.correction_pivots,
        ]
        for ref in refs:
            expected = ref.candle
            if expected.timeframe != "M5":
                return f"unsupported_evidence_timeframe:{expected.timeframe}"
            actual = self._market_data_store.get_closed_candles(
                expected.broker_server,
                expected.symbol,
                "M5",
                start_utc=expected.candle_open_time_utc,
                end_utc=expected.candle_open_time_utc + timedelta(minutes=5),
                limit=1,
            )
            if not actual:
                return f"missing_evidence_candle:{ref.candle_id}"
            if actual[0] != expected:
                return f"changed_evidence_candle:{ref.candle_id}"
        return None
