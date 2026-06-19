from datetime import date, datetime, timezone

from app.pipeline.pipeline import _freshness_cutoff


def test_cutoff_24h_anchors_to_start_of_brief_date_utc() -> None:
    cutoff = _freshness_cutoff(date(2026, 6, 19), hours=24)
    assert cutoff == datetime(2026, 6, 19, 0, 0, 0, tzinfo=timezone.utc)


def test_cutoff_36h_extends_to_previous_noon_utc() -> None:
    """36h 윈도우 → US 야간 이벤트(전날 21:00 UTC ≈ 06:00 KST)까지 포함."""
    cutoff = _freshness_cutoff(date(2026, 6, 19), hours=36)
    assert cutoff == datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)


def test_cutoff_returns_utc_aware_datetime() -> None:
    cutoff = _freshness_cutoff(date(2026, 6, 19), hours=24)
    assert cutoff.tzinfo is timezone.utc
