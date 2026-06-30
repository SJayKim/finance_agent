from datetime import date, datetime, timezone

from app.pipeline.pipeline import _freshness_cutoff


def test_cutoff_24h_anchors_to_start_of_brief_date_kst() -> None:
    # brief_date 종일은 KST 기준 → 6/19 시작(=6/18 15:00 UTC)이 24h 컷오프.
    cutoff = _freshness_cutoff(date(2026, 6, 19), hours=24)
    assert cutoff == datetime(2026, 6, 18, 15, 0, 0, tzinfo=timezone.utc)


def test_cutoff_36h_extends_to_previous_kst_window() -> None:
    """36h 윈도우 → 6/20 00:00 KST에서 36h 전 = 6/18 03:00 UTC."""
    cutoff = _freshness_cutoff(date(2026, 6, 19), hours=36)
    assert cutoff == datetime(2026, 6, 18, 3, 0, 0, tzinfo=timezone.utc)


def test_cutoff_returns_utc_aware_datetime() -> None:
    cutoff = _freshness_cutoff(date(2026, 6, 19), hours=24)
    assert cutoff.tzinfo is timezone.utc


def test_cutoff_includes_brief_date_morning_kst_news() -> None:
    """회귀: KST 오전 수집분(전날 저녁 UTC 발행)이 24h 컷오프 안에 들어와야 한다.

    버그 재현: brief_date=6/23(KST)에서 6/22 23:01 UTC(=6/23 08:01 KST 오늘 아침 뉴스)는
    포함돼야 한다. UTC 앵커일 때 컷오프가 6/23 00:00 UTC라 이 문서가 잘려 클러스터가 0이 됐다.
    """
    cutoff = _freshness_cutoff(date(2026, 6, 23), hours=24)
    morning_kst_news = datetime(2026, 6, 22, 23, 1, 0, tzinfo=timezone.utc)
    assert morning_kst_news >= cutoff
