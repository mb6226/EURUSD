# Phase 8 — Session Eligibility and Risk Gate

## Scope

Phase 8 adds a deterministic, assessment-only gate after a Phase 7 PATTERN_CONFIRMED setup. It checks London/New York local session windows, durable one-setup-per-session reservations, and a daily risk budget. It does not create entry prices, orders, or execution instructions.

## Session definitions

- London: 08:00 inclusive to 12:00 exclusive in Europe/London.
- New York: 08:00 inclusive to 12:00 exclusive in America/New_York.
- IANA timezone data handles each market's DST rules independently.
- Session date is the local calendar date in that session's timezone.
- The shared daily risk date is the London local calendar date, so both sessions share one daily budget.

## Eligibility and reservation semantics

- Only PATTERN_CONFIRMED is eligible for the gate.
- Outside both windows returns OUTSIDE_SESSION; an unconfirmed pattern returns WAIT_SETUP.
- A confirmed setup reserves one slot for its session and 5 pips of risk.
- Reservation identity combines the correction lifecycle ID and M1 retest candle ID. Repeated polling is idempotent.
- A distinct second setup in the same session is blocked.
- A second 5-pip reservation in the same London risk date can bring daily risk to 10 pips; further reservations are blocked.
- Reservations are committed transactionally to a separate SQLite ledger and survive process restarts.
- Reservations are research eligibility records, not open positions or filled orders.

## Risk parameters

- Stop loss: 5 pips.
- Take profit: 50 pips (experimental target, not a profitability claim).
- Daily reserved risk budget: 10 pips.
- Trailing stop: disabled.
- Maximum one setup per session, two sessions per risk date.

## Safety boundary

Every result carries decision_authority=ASSESSMENT_ONLY, trade_authority=NONE, and order_execution=DISABLED. No BUY/SELL instruction, entry price, order request, or MT5 order function is added. A reservation only means the setup passed this research gate.

## Known limitations

- This is not a backtest and does not prove the SL/TP parameters are profitable.
- Spread/slippage constraints are not introduced because no explicit maximum-spread acceptance threshold has been approved.
- A reservation consumes session capacity even if no trade is executed; this is intentional for deterministic research accounting.
- Statistical validation and trade-outcome tracking remain later phases.
