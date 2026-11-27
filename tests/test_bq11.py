import json
from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import text
from streamlit.testing.v1 import AppTest

from test_bq12_postgres import engine  # noqa: F401 — existing isolated PostgreSQL fixture
from sidequests_analytics.bq11 import compute_bq11


def test_real_postgres_reports_only_verified_weekend_cohorts(engine):
    bogota = ZoneInfo("America/Bogota")
    date = datetime.now(bogota).date()
    # The previous Saturday is always within the window and guaranteed complete.
    date -= timedelta(days=(date.weekday() - 5) % 7 or 7)
    saturday = datetime.combine(date, time(hour=21), bogota)
    with engine.begin() as c:
        c.execute(text("alter table quests add column location_mode text"))
        c.execute(text("alter table user_quests add column completed_at timestamptz"))
        c.execute(text("insert into quests(id,category,location_mode) values "
                       "('physical','Food','gps'), ('anywhere','Food','anywhere')"))

        def add(*, block="paloquemao-market", millis=1_500_000, when=saturday,
                status="completed", quest="physical", duplicate=False, owner_mismatch=False,
                measured_weekend=date, user=None):
            user, attempt = user or uuid4(), uuid4()
            c.execute(text("insert into user_quests(id,user_id,quest_id,status,completed_at) "
                           "values (:attempt,:user,:quest,:status,:ts)"),
                      dict(attempt=attempt, user=user, quest=quest, status=status, ts=when))
            for repeat in range(2 if duplicate else 1):
                c.execute(text("insert into analytics_events(user_id,event_type,quest_id,occurred_at,metadata) "
                               "values (:user,'bq11_commercial_block_completed',:quest,:ts,cast(:details as jsonb))"),
                          dict(user=uuid4() if owner_mismatch else user, quest=quest, ts=when,
                               details=json.dumps(dict(attempt_id=str(attempt), platform="kotlin",
                                                       schema_version=1, block_id=block,
                                                       observed_ms=millis, weekend_start=str(measured_weekend)))))
            return user

        user = add(duplicate=True)
        add(user=user)
        for _ in range(4):
            add()
            add(block="usaquen-cra6a-c119")  # Suppressed below five distinct users.
        add(millis=1_200_000)
        add(millis="invalid")
        add(when=saturday - timedelta(days=1))
        add(status="abandoned")
        add(quest="anywhere")
        add(owner_mismatch=True)
        add(measured_weekend=date - timedelta(days=7))
        add(block="unmapped")
    assert compute_bq11(engine) == [{
        "block_id": "paloquemao-market",
        "commercial_block": "Paloquemao market block · Avenida Calle 19 #25-04",
        "qualifying_attempts": 6,
        "distinct_users": 5,
        "mean_observed_minutes": 25.0,
    }]


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
