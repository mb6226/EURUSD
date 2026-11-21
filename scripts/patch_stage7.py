from pathlib import Path
p=Path("scripts/daily_elliott_forecaster.py")
s=p.read_text(encoding="utf-8-sig")
s=s.replace(
'''def next_weekday_session(as_of: datetime) -> str:
    day = as_of.astimezone(NY).date() + timedelta(days=1)''',
'''def next_weekday_session(as_of: datetime, now_utc: datetime | None = None) -> str:
    reference_day = as_of.astimezone(NY).date()
    if now_utc is not None:
        reference_day = max(reference_day, now_utc.astimezone(NY).date())
    day = reference_day + timedelta(days=1)'''
)
s=s.replace(
'''def generate(max_snapshot_age_hours: float = 6.0) -> dict:
    market = latest_market_state()
    as_of = parse_time(market["as_of"])''',
'''def generate(max_snapshot_age_hours: float = 6.0, now_utc: datetime | None = None) -> dict:
    market = latest_market_state()
    as_of = parse_time(market["as_of"])
    now_utc = now_utc or datetime.now(timezone.utc)
    data_age_hours = max(0.0, (now_utc - as_of).total_seconds() / 3600)'''
)
s=s.replace(
'''    reasons = []
    if snapshot is None:''',
'''    reasons = []
    if data_age_hours > 24:
        reasons.append("market_data_stale_over_24_hours")
    if snapshot is None:'''
)
s=s.replace(
'''        "forecast_for_next_ny_weekday_session": next_weekday_session(as_of),''',
'''        "forecast_for_next_ny_weekday_session": next_weekday_session(as_of, now_utc),
        "market_data_age_hours_at_generation": round(data_age_hours, 2),'''
)
p.write_text(s, encoding="utf-8")
