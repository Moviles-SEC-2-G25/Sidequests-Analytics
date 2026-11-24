from pathlib import Path
import sys

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sidequests_analytics.bq12 import bq12_compare, bq12_headline, bq12_level


def _row(level, sponsor_type, acceptance, completion, **dims):
    row = dict(
        segment_level=level, sponsor_type=sponsor_type, business_category="all",
        quest_category="all", interest="all", interest_match="all",
        impressions=12, accepted_impressions=6, exposed_users=4,
        acceptance_rate_pct=acceptance, accepted_attempts=6, completed_attempts=3,
        abandoned_attempts=1, open_attempts=2, attempting_users=3,
        completion_rate_pct=completion, resolved_completion_rate_pct=None,
        abandonment_rate_pct=None, acceptance_sample_ok=acceptance is not None,
        completion_sample_ok=completion is not None,
        acceptance_rate_vs_non_sponsored_pp=None, completion_rate_vs_non_sponsored_pp=None,
        window_days=30, min_impressions=10, min_attempts=5,
    )
    row.update(dims)
    return row


ROWS = [
    _row("overall", "sponsored", 50.0, 50.0,
         acceptance_rate_vs_non_sponsored_pp=10.0, completion_rate_vs_non_sponsored_pp=-5.0),
    _row("overall", "non_sponsored", 40.0, 55.0),
    _row("business_category", "sponsored", 50.0, None, business_category="fitness_and_recreation"),
    _row("business_category", "sponsored", None, None, business_category="food_and_beverage", impressions=0),
    _row("business_category", "non_sponsored", 40.0, 55.0, business_category="none"),
    _row("interest_match", "sponsored", 60.0, None, interest_match="matched"),
    _row("interest", "sponsored", 50.0, 50.0, interest="food"),
    _row("interest", "non_sponsored", 40.0, None, interest="food"),
    _row("interest", "sponsored", None, None, interest="art"),
    _row("business_category_x_interest", "sponsored", 50.0, None,
         business_category="fitness_and_recreation", interest="food"),
    _row("business_category_x_interest", "non_sponsored", 40.0, None, business_category="none", interest="food"),
]

WEEKLY = [
    dict(week_start="2026-11-09", sponsor_type="sponsored", impressions=3, acceptance_rate_pct=None),
    dict(week_start="2026-11-09", sponsor_type="non_sponsored", impressions=12, acceptance_rate_pct=25.0),
    dict(week_start="2026-11-16", sponsor_type="sponsored", impressions=11, acceptance_rate_pct=45.45),
    dict(week_start="2026-11-16", sponsor_type="non_sponsored", impressions=0, acceptance_rate_pct=None),
]


def test_headline_reads_the_overall_comparison():
    headline = bq12_headline(ROWS)
    assert headline["sponsored"]["acceptance_rate_pct"] == 50.0
    assert headline["non_sponsored"]["completion_rate_pct"] == 55.0
    assert (headline["acceptance_gap_pp"], headline["completion_gap_pp"]) == (10.0, -5.0)
    assert headline["comparable"] is True


def test_headline_is_not_comparable_without_a_rate_on_both_sides():
    rows = [_row("overall", "sponsored", None, 50.0), _row("overall", "non_sponsored", 40.0, 55.0)]
    assert bq12_headline(rows)["comparable"] is False
    assert bq12_headline([])["comparable"] is False


def test_compare_pivots_sponsor_types_and_keeps_missing_rates_empty():
    wide = bq12_compare(ROWS, "interest", "interest", "acceptance_rate_pct")
    assert list(wide.columns) == ["sponsored", "non_sponsored"]
    assert wide.loc["food", "sponsored"] == 50.0
    assert pd.isna(wide.loc["art", "sponsored"])  # no rate, not 0 %
    assert pd.isna(wide.loc["art", "non_sponsored"])
    assert bq12_level(ROWS, "quest_category").empty


def test_dashboard_renders_bq12_and_its_weekly_trend(monkeypatch):
    from sidequests_analytics import db
    stored = pd.DataFrame([
        dict(bq_key="BQ12", computed_at="fixture", payload={"rows": ROWS}),
        dict(bq_key="BQ12_WEEKLY", computed_at="fixture", payload={"rows": WEEKLY}),
    ])
    monkeypatch.setattr(db, "get_engine", lambda: object())
    monkeypatch.setattr(pd, "read_sql", lambda *args, **kwargs: stored)
    app = AppTest.from_file(str(ROOT / "dashboard_app.py")).run(timeout=20)
    assert not app.exception
    assert [item.value for item in app.subheader] == ["BQ12", "BQ12_WEEKLY"]
    assert [metric.value for metric in app.metric] == ["50.0%", "40.0%", "50.0%", "55.0%"]
    # business category, two interest charts, heatmap, weekly line
    assert len(app.get("arrow_vega_lite_chart")) == 5
    assert len(app.table) == 1
    assert len(app.dataframe) == 2
    assert not app.info


def test_dashboard_says_when_bq12_has_no_comparable_sample(monkeypatch):
    from sidequests_analytics import db
    rows = [_row("overall", "sponsored", None, None, impressions=3),
            _row("overall", "non_sponsored", None, None, impressions=4)]
    stored = pd.DataFrame([dict(bq_key="BQ12", computed_at="fixture", payload={"rows": rows})])
    monkeypatch.setattr(db, "get_engine", lambda: object())
    monkeypatch.setattr(pd, "read_sql", lambda *args, **kwargs: stored)
    app = AppTest.from_file(str(ROOT / "dashboard_app.py")).run(timeout=20)
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["—", "—", "—", "—"]
    assert len(app.info) == 1
    assert "Not enough sample" in app.info[0].value
