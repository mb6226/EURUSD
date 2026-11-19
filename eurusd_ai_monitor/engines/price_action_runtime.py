from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from eurusd_ai_monitor.engines.price_action_coordinator import (
    PriceActionCoordinator,
)
from eurusd_ai_monitor.engines.technical_engine import (
    TechnicalEngine,
    TechnicalStructure,
)
from eurusd_ai_monitor.models.correction_lifecycle import (
    CorrectionLifecycle,
    LifecycleState,
    TransitionResult,
)
from eurusd_ai_monitor.models.market_snapshot import MarketSnapshot
from eurusd_ai_monitor.storage.lifecycle_store import (
    LifecycleConcurrencyConflict,
    LifecycleRevisionConflict,
    LifecycleSaveResult,
    LifecycleStore,
    LifecycleStoreStatus,
)
from eurusd_ai_monitor.strategy_config import StrategyConfig


class RecoveryStatus(str, Enum):
    NORMAL = "NORMAL"
    RECONCILIATION = "RECONCILIATION"
    QUARANTINED = "QUARANTINED"


class PriceActionRuntimeStatus(str, Enum):
    PROCESSED = "PROCESSED"
    NO_LIFECYCLE = "NO_LIFECYCLE"
    WAIT_INVALID_CONTEXT = "WAIT_INVALID_CONTEXT"
    WAIT_RECOVERY = "WAIT_RECOVERY"
    WAIT_VERSION_MISMATCH = "WAIT_VERSION_MISMATCH"
    WAIT_REVISION_CONFLICT = "WAIT_REVISION_CONFLICT"
    WAIT_CONCURRENCY_CONFLICT = "WAIT_CONCURRENCY_CONFLICT"
    ERROR = "ERROR"


class RecoveryGate(Protocol):
    """Read-only gate implemented by the Phase 3.5.2 recovery manager."""

    def get_status(self, broker_server: str, symbol: str) -> RecoveryStatus:
        ...


@dataclass(frozen=True)
class PriceActionRuntimeResult:
    status: PriceActionRuntimeStatus
    broker_server: str
    symbol: str
    evaluated_at_utc: datetime
    technical_structure: TechnicalStructure | None = None
    transition: TransitionResult | None = None
    lifecycle_id: str | None = None
    lifecycle_state: LifecycleState | None = None
    persistence_status: LifecycleStoreStatus | None = None
    recovery_status: RecoveryStatus | None = None
    revision_watermark: int | None = None
    record_version: int | None = None
    state_version: int | None = None
    reason_codes: tuple[str, ...] = ()
    trade_authority: str = "NONE"

    def __post_init__(self) -> None:
        if not isinstance(self.status, PriceActionRuntimeStatus):
            raise TypeError("status must be a PriceActionRuntimeStatus")
        if not isinstance(self.broker_server, str) or not self.broker_server.strip():
            raise ValueError("broker_server must be non-empty")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be non-empty")
        if not isinstance(self.evaluated_at_utc, datetime):
            raise TypeError("evaluated_at_utc must be a datetime")
        if (
            self.evaluated_at_utc.tzinfo is None
            or self.evaluated_at_utc.utcoffset() is None
        ):
            raise ValueError("evaluated_at_utc must be timezone-aware")
        if self.technical_structure is not None and not isinstance(
            self.technical_structure, TechnicalStructure
        ):
            raise TypeError("technical_structure must be TechnicalStructure or None")
        if self.transition is not None and not isinstance(
            self.transition, TransitionResult
        ):
            raise TypeError("transition must be TransitionResult or None")
        if self.lifecycle_state is not None and not isinstance(
            self.lifecycle_state, LifecycleState
        ):
            raise TypeError("lifecycle_state must be LifecycleState or None")
        if self.persistence_status is not None and not isinstance(
            self.persistence_status, LifecycleStoreStatus
        ):
            raise TypeError("persistence_status must be LifecycleStoreStatus or None")
        if self.recovery_status is not None and not isinstance(
            self.recovery_status, RecoveryStatus
        ):
            raise TypeError("recovery_status must be RecoveryStatus or None")
        if not isinstance(self.reason_codes, tuple) or any(
            not isinstance(code, str) or not code.strip()
            for code in self.reason_codes
        ):
            raise ValueError("reason_codes must be a tuple of non-empty strings")
        if self.trade_authority != "NONE":
            raise ValueError("PriceActionRuntime cannot grant trade authority")


class PriceActionRuntime:
    """Coordinates technical analysis, PA lifecycle evaluation and persistence.

    This service deliberately does not integrate with the legacy decision
    engine and cannot create, modify, or execute a trading order.
    """

    def __init__(
        self,
        technical_engine: TechnicalEngine,
        coordinator: PriceActionCoordinator,
        lifecycle_store: LifecycleStore,
        config: StrategyConfig,
        recovery_gate: RecoveryGate,
    ) -> None:
        if not isinstance(technical_engine, TechnicalEngine):
            raise TypeError("technical_engine must be a TechnicalEngine")
        if not isinstance(coordinator, PriceActionCoordinator):
            raise TypeError("coordinator must be a PriceActionCoordinator")
        if not isinstance(lifecycle_store, LifecycleStore):
            raise TypeError("lifecycle_store must be a LifecycleStore")
        if not isinstance(config, StrategyConfig):
            raise TypeError("config must be a StrategyConfig")
        if not callable(getattr(recovery_gate, "get_status", None)):
            raise TypeError("recovery_gate must provide get_status(broker_server, symbol)")
        self._technical_engine = technical_engine
        self._coordinator = coordinator
        self._lifecycle_store = lifecycle_store
        self._config = config
        self._recovery_gate = recovery_gate

    def process(self, snapshot: MarketSnapshot) -> PriceActionRuntimeResult:
        if not isinstance(snapshot, MarketSnapshot):
            raise TypeError("snapshot must be a MarketSnapshot")

        if not snapshot.quality.is_valid:
            return self._result(
                snapshot,
                PriceActionRuntimeStatus.WAIT_INVALID_CONTEXT,
                reason_codes=("MARKET_CONTEXT_QUALITY_GATE_FAILED", *snapshot.quality.issues),
            )

        try:
            recovery_status = self._recovery_gate.get_status(
                snapshot.broker_server, snapshot.symbol
            )
            if not isinstance(recovery_status, RecoveryStatus):
                raise TypeError("recovery gate returned an unsupported status")
            if recovery_status is not RecoveryStatus.NORMAL:
                return self._result(
                    snapshot,
                    PriceActionRuntimeStatus.WAIT_RECOVERY,
                    recovery_status=recovery_status,
                    reason_codes=(f"RECOVERY_STATUS_{recovery_status.value}",),
                )

            # Read the active snapshot, optimistic versions and M5 revision
            # watermark together before analysis. save_transition rechecks the
            # watermark and record_version inside its write transaction.
            stream = self._lifecycle_store.load_stream_state(
                snapshot.broker_server, snapshot.symbol
            )
            active_record = stream.active_record
            active_lifecycle = (
                active_record.lifecycle if active_record is not None else None
            )

            structure = self._technical_engine.analyze_snapshot(snapshot)
            if active_lifecycle is not None and (
                active_lifecycle.algorithm_version != structure.algorithm_version
                or active_lifecycle.parameter_version != structure.parameter_version
            ):
                return self._result(
                    snapshot,
                    PriceActionRuntimeStatus.WAIT_VERSION_MISMATCH,
                    technical_structure=structure,
                    lifecycle=active_lifecycle,
                    recovery_status=recovery_status,
                    revision_watermark=stream.revision_watermark,
                    record_version=active_record.record_version,
                    state_version=active_record.state_version,
                    reason_codes=("ACTIVE_LIFECYCLE_VERSION_MISMATCH",),
                )

            coordinated = self._coordinator.process(
                structure=structure,
                m5_candles=snapshot.m5_candles,
                active_lifecycle=active_lifecycle,
                pip_size=self._config.pip_size,
                min_correction_pips=self._config.min_correction_pips,
                max_correction_ratio=self._config.max_correction_ratio,
                expiry_bars=self._config.setup_expiry_bars,
            )
            transition = coordinated.transition
            lifecycle = transition.lifecycle

            if lifecycle is None:
                return self._result(
                    snapshot,
                    PriceActionRuntimeStatus.NO_LIFECYCLE,
                    technical_structure=structure,
                    transition=transition,
                    recovery_status=recovery_status,
                    revision_watermark=stream.revision_watermark,
                    reason_codes=transition.reason_codes,
                )

            expected_record_version = (
                active_record.record_version if active_record is not None else None
            )
            saved = self._lifecycle_store.save_transition(
                transition,
                expected_record_version=expected_record_version,
                revision_watermark=stream.revision_watermark,
                created_at_utc=snapshot.timestamp_utc,
            )
            return self._result(
                snapshot,
                PriceActionRuntimeStatus.PROCESSED,
                technical_structure=structure,
                transition=transition,
                lifecycle=lifecycle,
                saved=saved,
                recovery_status=recovery_status,
                revision_watermark=stream.revision_watermark,
                fallback_record_version=(
                    active_record.record_version if active_record is not None else None
                ),
                fallback_state_version=(
                    active_record.state_version if active_record is not None else None
                ),
                reason_codes=transition.reason_codes,
            )
        except LifecycleRevisionConflict:
            return self._result(
                snapshot,
                PriceActionRuntimeStatus.WAIT_REVISION_CONFLICT,
                reason_codes=("M5_CANDLE_REVISION_DURING_ANALYSIS",),
            )
        except LifecycleConcurrencyConflict:
            return self._result(
                snapshot,
                PriceActionRuntimeStatus.WAIT_CONCURRENCY_CONFLICT,
                reason_codes=("LIFECYCLE_RECORD_VERSION_CONFLICT",),
            )
        except Exception as exc:
            return self._result(
                snapshot,
                PriceActionRuntimeStatus.ERROR,
                reason_codes=(f"PRICE_ACTION_RUNTIME_ERROR:{type(exc).__name__}:{exc}",),
            )

    @staticmethod
    def _result(
        snapshot: MarketSnapshot,
        status: PriceActionRuntimeStatus,
        *,
        technical_structure: TechnicalStructure | None = None,
        transition: TransitionResult | None = None,
        lifecycle: CorrectionLifecycle | None = None,
        saved: LifecycleSaveResult | None = None,
        recovery_status: RecoveryStatus | None = None,
        revision_watermark: int | None = None,
        record_version: int | None = None,
        state_version: int | None = None,
        fallback_record_version: int | None = None,
        fallback_state_version: int | None = None,
        reason_codes: tuple[str, ...] = (),
    ) -> PriceActionRuntimeResult:
        if saved is not None:
            record_version = saved.record_version
            state_version = saved.state_version
        elif record_version is None:
            record_version = fallback_record_version
        if saved is None and state_version is None:
            state_version = fallback_state_version

        return PriceActionRuntimeResult(
            status=status,
            broker_server=snapshot.broker_server,
            symbol=snapshot.symbol,
            evaluated_at_utc=snapshot.timestamp_utc,
            technical_structure=technical_structure,
            transition=transition,
            lifecycle_id=lifecycle.lifecycle_id if lifecycle is not None else None,
            lifecycle_state=lifecycle.state if lifecycle is not None else None,
            persistence_status=saved.status if saved is not None else None,
            recovery_status=recovery_status,
            revision_watermark=revision_watermark,
            record_version=record_version,
            state_version=state_version,
            reason_codes=reason_codes,
        )
