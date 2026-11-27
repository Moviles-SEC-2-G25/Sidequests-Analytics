import json
from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import text
from streamlit.testing.v1 import AppTest

from test_bq12_postgres import engine  # noqa: F401 — existing isolated PostgreSQL fixture
from sidequests_analytics.bq11 import compute_bq11

BOGOTA = ZoneInfo("America/Bogota")
# The previous Saturday is always within the window and guaranteed complete.
DATE = datetime.now(BOGOTA).date()
DATE -= timedelta(days=(DATE.weekday() - 5) % 7 or 7)
SATURDAY = datetime.combine(DATE, time(hour=21), BOGOTA)
PALOQUEMAO = "Paloquemao market block · Avenida Calle 19 #25-04"


@pytest.fixture
def db(engine):  # noqa: F811
    with engine.begin() as c:
        c.execute(text("alter table quests add column if not exists location_mode text"))
        c.execute(text("alter table user_quests add column if not exists completed_at timestamptz"))
        c.execute(text("truncate analytics_events, user_quests, quests restart identity cascade"))
        c.execute(text("insert into quests(id,category,location_mode) values "
                       "('physical','Food','gps'), ('anywhere','Food','anywhere')"))
    return engine


def add(c, *, block="paloquemao-market", millis=1_500_000, when=SATURDAY,
        status="completed", quest="physical", platforms=("kotlin",), owner_mismatch=False,
        measured_weekend=DATE, user=None):
    """One attempt, reported by one event per entry of `platforms` (None = key absent)."""
    user, attempt = user or uuid4(), uuid4()
    c.execute(text("insert into user_quests(id,user_id,quest_id,status,completed_at) "
                   "values (:attempt,:user,:quest,:status,:ts)"),
              dict(attempt=attempt, user=user, quest=quest, status=status, ts=when))
    for platform in platforms:
        details = dict(attempt_id=str(attempt), schema_version=1, block_id=block,
                       observed_ms=millis, weekend_start=str(measured_weekend))
        if platform is not None:
            details["platform"] = platform
        c.execute(text("insert into analytics_events(user_id,event_type,quest_id,occurred_at,metadata) "
                       "values (:user,'bq11_commercial_block_completed',:quest,:ts,cast(:details as jsonb))"),
                  dict(user=uuid4() if owner_mismatch else user, quest=quest, ts=when,
                       details=json.dumps(details)))
    return user


def paloquemao(attempts, users):
    return [{
        "block_id": "paloquemao-market",
        "commercial_block": PALOQUEMAO,
        "qualifying_attempts": attempts,
        "distinct_users": users,
        "mean_observed_minutes": 25.0,
    }]


def test_real_postgres_reports_only_verified_weekend_cohorts(db):
    with db.begin() as c:
        user = add(c, platforms=("kotlin", "kotlin"))
        add(c, user=user)
        for _ in range(4):
            add(c)
            add(c, block="usaquen-cra6a-c119")  # Suppressed below five distinct users.
        add(c, millis=1_200_000)
        add(c, millis="invalid")
        add(c, when=SATURDAY - timedelta(days=1))
        add(c, status="abandoned")
        add(c, quest="anywhere")
        add(c, owner_mismatch=True)
        add(c, measured_weekend=DATE - timedelta(days=7))
        add(c, block="unmapped")
    assert compute_bq11(db) == paloquemao(attempts=6, users=5)


def test_a_valid_flutter_event_counts_like_a_kotlin_one(db):
    with db.begin() as c:
        for _ in range(4):
            add(c)
        add(c, platforms=("flutter",))  # the fifth user, so the block is reported
    assert compute_bq11(db) == paloquemao(attempts=5, users=5)


def test_an_unknown_or_missing_platform_does_not_count(db):
    with db.begin() as c:
        for _ in range(4):
            add(c)
        add(c, platforms=("ios",))
        add(c, platforms=(None,))
    assert compute_bq11(db) == []  # only four valid users: suppressed


def test_the_same_attempt_counts_once(db):
    with db.begin() as c:
        add(c, platforms=("flutter", "flutter"))  # Flutter delivery retried
        add(c, platforms=("kotlin", "flutter"))  # same attempt reported by both clients
        for _ in range(3):
            add(c, platforms=("flutter",))
    assert compute_bq11(db) == paloquemao(attempts=5, users=5)


def test_dashboard_displays_aggregate_and_loads_live_rows(monkeypatch):
    from sidequests_analytics import bq11, db

    result = [dict(block_id="pilot", commercial_block="Pilot block", qualifying_attempts=6,
                   distinct_users=5, mean_observed_minutes=24)]
    monkeypatch.setattr(db, "get_engine", lambda: object())
    monkeypatch.setattr(bq11, "compute_bq11", lambda _: result)
    monkeypatch.setattr(pd, "read_sql", lambda *args, **kwargs: pd.DataFrame([
        dict(bq_key="BQ11", computed_at="fixture", payload={"rows": result})
    ]))
    app = AppTest.from_file("dashboard_app.py").run(timeout=20)
    assert not app.exception
    assert len(app.dataframe) == 1
    app.button(key="refresh_bq11").click().run(timeout=20)
    assert not app.exception
    assert len(app.dataframe) == 2
