from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from sidequests_analytics import pipeline
from sidequests_analytics.queries import BQ2_GROUP_CHALLENGES_SQL


def test_bq2_query_counts_members_and_failed_requests_not_fake_events():
    sql = BQ2_GROUP_CHALLENGES_SQL.lower()
    assert "sidequests_group_private.members" in sql
    assert "sidequests_group_private.operations" in sql
    assert "filter(where not succeeded)" in sql
    assert "nullif(o.attempts,0)" in sql
    assert "m.progress=c.total_steps" in sql
    assert "recommendation_shown" not in sql


def test_missing_failure_rate_serializes_as_null(monkeypatch):
    frame = pd.DataFrame([{"row_type":"operation","operation":"join","attempts":0,
                           "failure_rate_pct":float("nan")}])
    monkeypatch.setattr(pd, "read_sql", lambda *args, **kwargs: frame)
    assert pipeline.compute_bq2(object())[0]["failure_rate_pct"] is None


def test_pipeline_exposes_bq2():
    source = Path(pipeline.__file__).read_text()
    assert 'store_bq_result(engine, "BQ2", bq2)' in source
    assert 'elif args.job == "bq2"' in source


def test_bq2_postgresql_counts_actual_members_and_handles_missing_outcomes():
    import os
    import pytest
    from sqlalchemy import create_engine, text
    url = os.getenv("BQ2_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Isolated PostgreSQL test database configured by CI only")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                conn.execute(text("create schema sidequests_group_private"))
                for ddl in [
                    "create table public.quests(id text primary key,title text)",
                    "create table public.analytics_events(user_id uuid,event_type text,metadata jsonb,occurred_at timestamptz)",
                    "create table sidequests_group_private.challenges(id uuid primary key,quest_id text,owner_id uuid,expires_at timestamptz,created_at timestamptz,total_steps int)",
                    "create table sidequests_group_private.members(challenge_id uuid,user_id uuid,progress int)",
                    "create table sidequests_group_private.operations(user_id uuid,request_id uuid,operation text,succeeded bool,occurred_at timestamptz)",
                ]:
                    conn.execute(text(ddl))
                a = "00000000-0000-0000-0000-000000000001"
                b = "00000000-0000-0000-0000-000000000002"
                cid = "00000000-0000-0000-0000-000000000003"
                request = "00000000-0000-0000-0000-000000000004"
                lost = "00000000-0000-0000-0000-000000000005"
                conn.execute(text("insert into public.quests values ('group','Fixture group')"))
                conn.execute(text("insert into sidequests_group_private.challenges values (:cid,'group',:a,now()+interval '7 days',now(),2)"), {"cid":cid,"a":a})
                conn.execute(text("insert into sidequests_group_private.members values (:cid,:a,0),(:cid,:b,2)"), {"cid":cid,"a":a,"b":b})
                conn.execute(text("insert into sidequests_group_private.operations values (:b,:request,'join',true,now()),(:a,gen_random_uuid(),'join',false,now())"), {"b":b,"a":a,"request":request})
                for req in [request, request, lost]:
                    conn.execute(text("insert into public.analytics_events values (:b,'group_challenge_client_unconfirmed',jsonb_build_object('request_id',cast(:req as text),'operation','join'),now())"), {"b":b,"req":req})
                rows = pipeline.compute_bq2(conn)
                join = next(r for r in rows if r["operation"]=="join")
                assert join["attempts"]==2
                assert join["successes"]==1
                assert join["failures"]==1
                assert join["failure_rate_pct"]==50
                assert join["client_unconfirmed"]==2
                assert join["no_server_record"]==1
                create = next(r for r in rows if r["operation"]=="create")
                assert create["attempts"]==0 and create["failure_rate_pct"] is None
                group = next(r for r in rows if r["row_type"]=="challenge")
                assert group["participants"]==2
                assert group["joined_non_creators"]==1
                assert group["completed_participants"]==1
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
