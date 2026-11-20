from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from eurusd_ai_monitor.engines.multi_horizon_forecasting_engine import MultiHorizonForecastingEngine


def build_multi_horizon_forecast(snapshot: Mapping[str, Any],
                                 central_scenario: Mapping[str, Any] | None = None,
                                 *, engine: MultiHorizonForecastingEngine | None = None) -> dict[str, Any]:
    """Build a forecast from one strict PIT snapshot and its matching central scenario."""
    selected = engine or MultiHorizonForecastingEngine()
    if not isinstance(selected, MultiHorizonForecastingEngine):
        raise TypeError("engine must be a MultiHorizonForecastingEngine")
    return selected.assess(snapshot, central_scenario)
