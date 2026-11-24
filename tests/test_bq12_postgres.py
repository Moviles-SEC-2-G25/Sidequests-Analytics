"""Runs BQ12 for real against a throwaway PostgreSQL cluster, as test_bq6_postgres
does: grouping sets, jsonb, `filter` and security_invoker views need PostgreSQL.
It never uses DATABASE_URL, a running PostgreSQL service or Supabase.

The data mimics both clients: Kotlin sends `recommendation_*` with an event_id
and `source = rpc_viewport` and saves interests capitalized ('Outdoors'); Flutter
sends batch_id/variant/social_level_source and saves them lowercase ('outdoors').
"""

import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sidequests_analytics.pipeline import compute_bq12, compute_bq12_weekly, store_bq_result

VIEWS_SQL = Path(__file__).parent.parent / "docs" / "BQ12_SUPABASE_VIEWS.sql"

SCHEMA = """
create role anon;
create role authenticated;
create table public.quests (
  id text primary key,
  category text not null,
  tags text[] not null default '{}',
  is_sponsored boolean not null default false,
  sponsor_business_category text,
  is_active boolean not null default true
);
create table public.user_preferences (
  user_id uuid primary key,
  interests text[] not null default '{}'
);
create table public.user_quests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  quest_id text not null references public.quests(id),
  status text not null,
  accepted_at timestamptz not null default now()
);
create table public.analytics_events (
  id bigint generated always as identity primary key,
  user_id uuid not null,
  session_id uuid,
  event_type text not null,
  quest_id text references public.quests(id) on delete set null,
  category text,
  occurred_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb
);
create schema analytics;
create table analytics.bq_results (
  id bigint generated always as identity primary key,
  bq_key text not null,
  computed_at timestamptz not null default now(),
  window_start timestamptz,
  window_end timestamptz,
  payload jsonb not null default '{}'::jsonb
);
revoke all on schema analytics from anon, authenticated;
"""

# Sponsored in two business categories plus one not yet classified; the rest
# are ordinary quests. 'old-sponsor' ended its campaign (inactive).
CATALOGUE = [
    ("climb", "Movement", ["movement", "sport", "sponsored"], True, "fitness_and_recreation", True),
    ("latte", "Food", ["food", "coffee", "sponsored"], True, "food_and_beverage", True),
    ("mystery", "Art", ["art", "sponsored"], True, None, True),
    ("old-sponsor", "Learning", ["learning"], True, "retail", False),
    ("ramen", "Food", ["food", "urban"], False, None, True),
    ("mural", "Art", ["art", "campus"], False, None, True),
    ("garden", "Outdoors", ["nature"], False, None, True),
]

NOW = datetime.now(timezone.utc)
KOTLIN_USER = "00000000-0000-0000-0000-00000000000a"
FLUTTER_USER = "00000000-0000-0000-0000-00000000000b"
OTHER_USER = "00000000-0000-0000-0000-00000000000c"
SESSION_1 = "00000000-0000-0000-0001-000000000001"
SESSION_2 = "00000000-0000-0000-0001-000000000002"
LOW = {"min_impressions": 1, "min_attempts": 1}


def _find_postgres_bin():
    candidates = [os.getenv("PG_BIN")]
    on_path = shutil.which("initdb")
    if on_path:
        candidates.append(str(Path(on_path).parent))
    candidates += sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin"), reverse=True)
    candidates += sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True)
    suffix = ".exe" if sys.platform == "win32" else ""
    for folder in candidates:
        if folder and (Path(folder) / f"initdb{suffix}").exists():
            return Path(folder)
    return None


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    binaries = _find_postgres_bin()
    if binaries is None:
        message = "PostgreSQL no encontrado; instala PostgreSQL para correr los tests de BQ12"
        # On a developer's machine that's a skip; CI must really run this test.
        if os.getenv("CI"):
            pytest.fail(message)
        pytest.skip(message)

    data = tmp_path_factory.mktemp("bq12_cluster") / "data"
    port = _free_port()
    subprocess.run(
        [binaries / "initdb", "-D", data, "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C"],
        check=True,
        capture_output=True,
    )
    # UTC like Supabase: weeks start on Monday 00:00 UTC.
    with open(data / "postgresql.conf", "a", encoding="utf-8") as settings:
        settings.write(
            f"\nport = {port}\nlisten_addresses = '127.0.0.1'\nunix_socket_directories = ''\ntimezone = 'UTC'\n"
        )
    subprocess.run(
        [binaries / "pg_ctl", "-D", data, "-w", "-l", data.parent / "server.log", "start"],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    engine = create_engine(f"postgresql+psycopg://postgres@127.0.0.1:{port}/postgres")
    try:
        with engine.begin() as connection:
            connection.execute(text(SCHEMA))
        yield engine
    finally:
        engine.dispose()
        subprocess.run(
            [binaries / "pg_ctl", "-D", data, "-m", "immediate", "-w", "stop"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


@pytest.fixture
def db(engine):
    with engine.begin() as connection:
        connection.execute(text(
            "truncate public.analytics_events, public.user_quests, public.user_preferences, "
            "public.quests, analytics.bq_results restart identity cascade"
        ))
        for quest_id, category, tags, sponsored, business, active in CATALOGUE:
            connection.execute(
                text(
                    "insert into public.quests (id, category, tags, is_sponsored, sponsor_business_category, is_active) "
                    "values (:id, :category, :tags, :sponsored, :business, :active)"
                ),
                {"id": quest_id, "category": category, "tags": tags, "sponsored": sponsored,
                 "business": business, "active": active},
            )
    return engine


def ago(days=0, hours=0, minutes=0):
    return NOW - timedelta(days=days, hours=hours, minutes=minutes)


def _event(db, event_type, user, session, quest, at, metadata):
    with db.begin() as connection:
        connection.execute(
            text(
                "insert into public.analytics_events (user_id, session_id, event_type, quest_id, occurred_at, metadata) "
                "values (:user, :session, :type, :quest, :at, cast(:metadata as jsonb))"
            ),
            {"user": user, "session": session, "type": event_type, "quest": quest, "at": at,
             "metadata": json.dumps(metadata)},
        )


def shown(db, user, quest, at, session=SESSION_1, client="flutter", rank=1):
    """recommendation_shown as each client sends it."""
    if client == "kotlin":
        metadata = {"batch_id": "kotlin-batch", "rank": rank, "variant": "control",
                    "source": "rpc_viewport", "event_id": str(uuid.uuid4())}
    else:
        metadata = {"variant": "diverse", "rank": rank, "batch_id": str(uuid.uuid4()),
                    "social_level_source": "profile"}
    _event(db, "recommendation_shown", user, session, quest, at, metadata)


def accepted(db, user, quest, at, session=SESSION_1, client="flutter"):
    """recommendation_accepted: Kotlin only adds event_id; Flutter adds BQ4 fields."""
    if client == "kotlin":
        metadata = {"event_id": str(uuid.uuid4())}
    else:
        metadata = {"start_path": "standard", "seconds_to_start": 12,
                    "interactions_to_start": 2, "batch_id": "flutter-batch"}
    _event(db, "recommendation_accepted", user, session, quest, at, metadata)


def attempt(db, user, quest, status, at):
    with db.begin() as connection:
        connection.execute(
            text("insert into public.user_quests (user_id, quest_id, status, accepted_at) "
                 "values (:user, :quest, :status, :at)"),
            {"user": user, "quest": quest, "status": status, "at": at},
        )


def interests(db, user, values):
    with db.begin() as connection:
        connection.execute(
            text("insert into public.user_preferences (user_id, interests) values (:user, :values)"),
            {"user": user, "values": values},
        )


def row(rows, level, sponsor_type, business_category="all", quest_category="all",
        interest="all", interest_match="all"):
    matches = [
        r for r in rows
        if r["segment_level"] == level
        and r["sponsor_type"] == sponsor_type
        and r["business_category"] == business_category
        and r["quest_category"] == quest_category
        and r["interest"] == interest
        and r["interest_match"] == interest_match
    ]
    assert len(matches) <= 1, matches
    return matches[0] if matches else None


def test_both_clients_count_in_the_same_funnel(db):
    shown(db, KOTLIN_USER, "climb", ago(days=2), client="kotlin", rank=1)
    shown(db, KOTLIN_USER, "ramen", ago(days=2), client="kotlin", rank=2)
    accepted(db, KOTLIN_USER, "climb", ago(days=2) + timedelta(minutes=3), client="kotlin")
    shown(db, FLUTTER_USER, "climb", ago(days=1), rank=1)
    shown(db, FLUTTER_USER, "ramen", ago(days=1), rank=2)
    accepted(db, FLUTTER_USER, "ramen", ago(days=1) + timedelta(minutes=1))

    rows = compute_bq12(db, **LOW)

    sponsored = row(rows, "overall", "sponsored")
    non_sponsored = row(rows, "overall", "non_sponsored")
    assert (sponsored["impressions"], sponsored["accepted_impressions"], sponsored["exposed_users"]) == (2, 1, 2)
    assert (non_sponsored["impressions"], non_sponsored["accepted_impressions"]) == (2, 1)
    assert sponsored["acceptance_rate_pct"] == 50.0
    assert non_sponsored["acceptance_rate_pct"] == 50.0
    assert sponsored["acceptance_rate_vs_non_sponsored_pp"] == 0.0


def test_reloads_count_one_impression_per_user_session_and_quest(db):
    for minutes in (30, 20, 10):  # the same list reloaded three times
        shown(db, FLUTTER_USER, "climb", ago(minutes=minutes))
    accepted(db, FLUTTER_USER, "climb", ago(minutes=5))
    shown(db, FLUTTER_USER, "climb", ago(days=3), session=SESSION_2)  # another session: another impression

    sponsored = row(compute_bq12(db, **LOW), "overall", "sponsored")

    assert sponsored["impressions"] == 2
    assert sponsored["accepted_impressions"] == 1
    assert sponsored["exposed_users"] == 1
    assert sponsored["acceptance_rate_pct"] == 50.0


def test_an_accept_counts_only_in_its_session_within_a_day_after_the_impression(db):
    shown(db, KOTLIN_USER, "climb", ago(days=3), client="kotlin")
    accepted(db, KOTLIN_USER, "climb", ago(days=3) + timedelta(minutes=5), session=SESSION_2, client="kotlin")
    shown(db, FLUTTER_USER, "climb", ago(days=5))
    accepted(db, FLUTTER_USER, "climb", ago(days=5) - timedelta(minutes=5))  # before it was shown
    accepted(db, FLUTTER_USER, "climb", ago(days=5) + timedelta(hours=25))  # too late
    accepted(db, OTHER_USER, "climb", ago(days=5) + timedelta(minutes=1))  # someone else

    sponsored = row(compute_bq12(db, **LOW), "overall", "sponsored")

    assert (sponsored["impressions"], sponsored["accepted_impressions"]) == (2, 0)
    assert sponsored["acceptance_rate_pct"] == 0.0  # exposed and never accepted: a real 0 %


def test_groups_without_exposure_have_no_rate_instead_of_zero(db):
    shown(db, FLUTTER_USER, "ramen", ago(days=1))
    attempt(db, FLUTTER_USER, "mystery", "completed", ago(days=1))  # accepted from the catalogue

    rows = compute_bq12(db, **LOW)

    # No sponsored impression at all: both sides of the comparison still appear.
    sponsored = row(rows, "overall", "sponsored")
    assert sponsored["impressions"] == 0
    assert sponsored["acceptance_rate_pct"] is None
    assert sponsored["acceptance_sample_ok"] is False
    assert sponsored["acceptance_rate_vs_non_sponsored_pp"] is None
    assert sponsored["completion_rate_pct"] == 100.0
    # Every business category of the active catalogue is listed, exposed or not.
    latte = row(rows, "business_category", "sponsored", business_category="food_and_beverage")
    assert (latte["impressions"], latte["accepted_attempts"]) == (0, 0)
    assert latte["acceptance_rate_pct"] is None and latte["completion_rate_pct"] is None
    # An ended campaign without activity isn't.
    assert row(rows, "business_category", "sponsored", business_category="retail") is None
    non_sponsored = row(rows, "overall", "non_sponsored")
    assert non_sponsored["completion_rate_pct"] is None and non_sponsored["accepted_attempts"] == 0


def test_business_category_is_none_for_non_sponsored_and_unspecified_when_missing(db):
    shown(db, FLUTTER_USER, "mystery", ago(days=1))
    shown(db, FLUTTER_USER, "climb", ago(days=1))
    shown(db, FLUTTER_USER, "mural", ago(days=1))
    shown(db, FLUTTER_USER, "old-sponsor", ago(days=1))  # inactive now, still sponsored history

    rows = compute_bq12(db, **LOW)

    by_business = {
        (r["sponsor_type"], r["business_category"]): r["impressions"]
        for r in rows if r["segment_level"] == "business_category"
    }
    assert by_business == {
        ("sponsored", "unspecified"): 1,
        ("sponsored", "fitness_and_recreation"): 1,
        ("sponsored", "food_and_beverage"): 0,
        ("sponsored", "retail"): 1,
        ("non_sponsored", "none"): 1,
    }
    # The activity category stays available to compare like with like.
    assert row(rows, "quest_category", "sponsored", quest_category="Art")["impressions"] == 1
    assert row(rows, "quest_category", "non_sponsored", quest_category="Art")["impressions"] == 1


def test_users_with_several_interests_count_once_per_interest_and_once_overall(db):
    # Kotlin casing, Flutter casing, a duplicate and stray spaces: three interests.
    interests(db, KOTLIN_USER, ["Outdoors", "food", "FOOD", " art "])
    interests(db, FLUTTER_USER, [])
    shown(db, KOTLIN_USER, "climb", ago(days=1), client="kotlin")
    accepted(db, KOTLIN_USER, "climb", ago(days=1) + timedelta(minutes=2), client="kotlin")
    attempt(db, KOTLIN_USER, "climb", "completed", ago(days=1))
    shown(db, FLUTTER_USER, "climb", ago(days=1))
    shown(db, OTHER_USER, "climb", ago(days=1))  # never saved preferences

    rows = compute_bq12(db, **LOW)

    overall = row(rows, "overall", "sponsored")
    assert (overall["impressions"], overall["accepted_impressions"], overall["accepted_attempts"]) == (3, 1, 1)
    by_interest = {
        r["interest"]: (r["impressions"], r["accepted_impressions"], r["accepted_attempts"])
        for r in rows if r["segment_level"] == "interest" and r["sponsor_type"] == "sponsored"
    }
    assert by_interest == {
        "outdoors": (1, 1, 1),
        "food": (1, 1, 1),
        "art": (1, 1, 1),
        "none_declared": (2, 0, 0),
    }
    grid = row(rows, "business_category_x_interest", "sponsored",
               business_category="fitness_and_recreation", interest="food")
    assert (grid["impressions"], grid["acceptance_rate_pct"]) == (1, 100.0)


def test_interest_match_follows_recommend_quests_rule(db):
    users = {
        "00000000-0000-0000-0000-000000000101": ["Movement"],  # category, Kotlin casing
        "00000000-0000-0000-0000-000000000102": ["sport"],  # one of the tags
        "00000000-0000-0000-0000-000000000103": ["food"],  # unrelated
    }
    for user, values in users.items():
        interests(db, user, values)
        shown(db, user, "climb", ago(days=1))
    shown(db, OTHER_USER, "climb", ago(days=1))

    rows = compute_bq12(db, **LOW)

    by_match = {
        r["interest_match"]: r["impressions"]
        for r in rows if r["segment_level"] == "interest_match" and r["sponsor_type"] == "sponsored"
    }
    assert by_match == {"matched": 2, "not_matched": 1, "none_declared": 1}


def test_completion_excludes_skips_and_attempts_outside_the_window(db):
    for status in ("completed", "abandoned", "in_progress", "accepted", "skipped"):
        attempt(db, FLUTTER_USER, "climb", status, ago(days=4))
    attempt(db, FLUTTER_USER, "climb", "completed", ago(days=31))

    sponsored = row(compute_bq12(db, **LOW), "overall", "sponsored")

    assert (sponsored["accepted_attempts"], sponsored["completed_attempts"],
            sponsored["abandoned_attempts"], sponsored["open_attempts"]) == (4, 1, 1, 2)
    assert sponsored["completion_rate_pct"] == 25.0
    assert sponsored["resolved_completion_rate_pct"] == 50.0
    assert sponsored["abandonment_rate_pct"] == 25.0
    assert sponsored["attempting_users"] == 1


def test_impressions_outside_the_window_are_ignored(db):
    shown(db, FLUTTER_USER, "climb", ago(days=31))
    shown(db, FLUTTER_USER, "climb", ago(days=10), session=SESSION_2)

    assert row(compute_bq12(db, **LOW), "overall", "sponsored")["impressions"] == 1
    assert row(compute_bq12(db, window_days=7, **LOW), "overall", "sponsored")["impressions"] == 0


def test_small_samples_keep_counts_but_no_rate(db):
    for index in range(9):
        shown(db, f"00000000-0000-0000-0002-{index:012d}", "climb", ago(days=1))
    for index in range(10):
        shown(db, f"00000000-0000-0000-0003-{index:012d}", "ramen", ago(days=1))
    for index in range(4):
        attempt(db, FLUTTER_USER, "climb", "completed", ago(days=1))
    for index in range(5):
        attempt(db, FLUTTER_USER, "ramen", "completed", ago(days=1))

    rows = compute_bq12(db)  # defaults: 10 impressions, 5 attempts

    sponsored = row(rows, "overall", "sponsored")
    non_sponsored = row(rows, "overall", "non_sponsored")
    assert (sponsored["impressions"], sponsored["acceptance_rate_pct"], sponsored["acceptance_sample_ok"]) == (9, None, False)
    assert (sponsored["accepted_attempts"], sponsored["completion_rate_pct"], sponsored["completion_sample_ok"]) == (4, None, False)
    assert (non_sponsored["impressions"], non_sponsored["acceptance_rate_pct"]) == (10, 0.0)
    assert (non_sponsored["accepted_attempts"], non_sponsored["completion_rate_pct"]) == (5, 100.0)
    assert sponsored["acceptance_rate_vs_non_sponsored_pp"] is None
    assert (sponsored["min_impressions"], sponsored["min_attempts"], sponsored["window_days"]) == (10, 5, 30)


def test_gaps_compare_with_non_sponsored_quests_of_the_same_segment(db):
    interests(db, FLUTTER_USER, ["food"])
    interests(db, KOTLIN_USER, ["Outdoors"])
    # food: sponsored 1/1 accepted, non-sponsored 0/1
    shown(db, FLUTTER_USER, "latte", ago(days=1))
    accepted(db, FLUTTER_USER, "latte", ago(days=1) + timedelta(minutes=1))
    shown(db, FLUTTER_USER, "ramen", ago(days=1))
    # outdoors: sponsored 0/1, non-sponsored 1/1
    shown(db, KOTLIN_USER, "climb", ago(days=1), client="kotlin")
    shown(db, KOTLIN_USER, "garden", ago(days=1), client="kotlin")
    accepted(db, KOTLIN_USER, "garden", ago(days=1) + timedelta(minutes=1), client="kotlin")

    rows = compute_bq12(db, **LOW)

    assert row(rows, "overall", "sponsored")["acceptance_rate_vs_non_sponsored_pp"] == 0.0
    assert row(rows, "interest", "sponsored", interest="food")["acceptance_rate_vs_non_sponsored_pp"] == 100.0
    assert row(rows, "interest", "sponsored", interest="outdoors")["acceptance_rate_vs_non_sponsored_pp"] == -100.0
    # A business category is compared with all non-sponsored quests ('none', 50 %).
    assert row(rows, "business_category", "sponsored",
               business_category="food_and_beverage")["acceptance_rate_vs_non_sponsored_pp"] == 50.0
    assert row(rows, "business_category_x_interest", "sponsored", business_category="food_and_beverage",
               interest="food")["acceptance_rate_vs_non_sponsored_pp"] == 100.0
    assert row(rows, "overall", "non_sponsored")["acceptance_rate_vs_non_sponsored_pp"] is None


def _monday(weeks_back):
    today = NOW.date()
    return today - timedelta(days=today.weekday()) - timedelta(weeks=weeks_back)


def test_weekly_trend_lists_every_week_and_leaves_empty_weeks_without_rate(db):
    tuesday_two_weeks_ago = datetime.combine(_monday(2) + timedelta(days=1), datetime.min.time(), timezone.utc)
    tuesday_last_week = datetime.combine(_monday(1) + timedelta(days=1), datetime.min.time(), timezone.utc)
    shown(db, FLUTTER_USER, "climb", tuesday_two_weeks_ago + timedelta(hours=9))
    accepted(db, FLUTTER_USER, "climb", tuesday_two_weeks_ago + timedelta(hours=9, minutes=1))
    shown(db, KOTLIN_USER, "ramen", tuesday_last_week + timedelta(hours=9), client="kotlin")
    attempt(db, KOTLIN_USER, "ramen", "abandoned", tuesday_last_week + timedelta(hours=10))
    shown(db, FLUTTER_USER, "climb", ago(days=60), session=SESSION_2)  # before the trend

    rows = compute_bq12_weekly(db, trend_weeks=4, **LOW)

    assert [(r["week_start"], r["sponsor_type"]) for r in rows] == [
        (_monday(weeks), sponsor_type)
        for weeks in (3, 2, 1, 0)
        for sponsor_type in ("sponsored", "non_sponsored")
    ]
    by_week = {(r["week_start"], r["sponsor_type"]): r for r in rows}
    assert by_week[(_monday(2), "sponsored")]["acceptance_rate_pct"] == 100.0
    assert by_week[(_monday(1), "non_sponsored")]["acceptance_rate_pct"] == 0.0
    assert by_week[(_monday(1), "non_sponsored")]["completion_rate_pct"] == 0.0
    empty = by_week[(_monday(3), "sponsored")]
    assert (empty["impressions"], empty["acceptance_rate_pct"], empty["completion_rate_pct"]) == (0, None, None)
    assert sum(r["impressions"] for r in rows) == 2


def test_stored_results_feed_the_supabase_views_and_stay_private(db):
    interests(db, FLUTTER_USER, ["food", "art"])
    interests(db, KOTLIN_USER, ["Food"])
    shown(db, FLUTTER_USER, "latte", ago(days=1))
    accepted(db, FLUTTER_USER, "latte", ago(days=1) + timedelta(minutes=1))
    shown(db, KOTLIN_USER, "ramen", ago(days=1), client="kotlin")
    attempt(db, FLUTTER_USER, "latte", "completed", ago(days=1))
    attempt(db, KOTLIN_USER, "ramen", "abandoned", ago(days=1))

    # The real job path: compute, then store as versioned JSON (no NaN allowed).
    store_bq_result(db, "BQ12", compute_bq12(db, **LOW))
    store_bq_result(db, "BQ12_WEEKLY", compute_bq12_weekly(db, trend_weeks=2, **LOW))
    with db.begin() as connection:
        connection.execute(text(VIEWS_SQL.read_text(encoding="utf-8")))
        connection.execute(text(VIEWS_SQL.read_text(encoding="utf-8")))  # re-runnable

    def query(sql):
        with db.connect() as connection:
            return [dict(r) for r in connection.execute(text(sql)).mappings()]

    overall = query("select * from analytics.bq12_overall")
    assert [r["sponsor_type"] for r in overall] == ["sponsored", "non_sponsored"]
    assert float(overall[0]["acceptance_rate_pct"]) == 100.0
    assert float(overall[1]["acceptance_rate_pct"]) == 0.0
    assert float(overall[0]["acceptance_rate_vs_non_sponsored_pp"]) == 100.0
    assert "user_id" not in overall[0]

    business = query("select business_category, impressions from analytics.bq12_by_business_category")
    assert business[-1] == {"business_category": "none", "impressions": 1}
    assert {"business_category": "food_and_beverage", "impressions": 1} in business

    by_interest = {r["interest"]: r for r in query("select * from analytics.bq12_by_interest")}
    assert set(by_interest) == {"food", "art"}
    assert float(by_interest["food"]["sponsored_acceptance_rate_pct"]) == 100.0
    assert float(by_interest["food"]["non_sponsored_acceptance_rate_pct"]) == 0.0
    assert by_interest["art"]["non_sponsored_acceptance_rate_pct"] is None  # never exposed
    assert by_interest["art"]["non_sponsored_impressions"] == 0

    grid = query("select segment_label, sponsor_type from analytics.bq12_by_category_interest")
    assert {"segment_label": "food_and_beverage · food", "sponsor_type": "sponsored"} in grid

    weekly = query("select * from analytics.bq12_weekly_trend")
    assert [r["week_start"] for r in weekly] == [_monday(1), _monday(0)]
    assert sum(r["sponsored_impressions"] + r["non_sponsored_impressions"] for r in weekly) == 2

    for role in ("anon", "authenticated"):
        for view in ("bq12_overall", "bq12_by_interest", "bq12_weekly_trend", "bq12_latest"):
            with db.connect() as connection:
                connection.execute(text(f"set role {role}"))
                with pytest.raises(ProgrammingError, match="permission denied"):
                    connection.execute(text(f"select * from analytics.{view}"))
                connection.rollback()


def test_the_latest_stored_result_wins(db):
    store_bq_result(db, "BQ12", [])
    shown(db, FLUTTER_USER, "climb", ago(days=1))
    store_bq_result(db, "BQ12", compute_bq12(db, **LOW))
    with db.begin() as connection:
        connection.execute(text(VIEWS_SQL.read_text(encoding="utf-8")))
        sponsored = connection.execute(text(
            "select impressions from analytics.bq12_overall where sponsor_type = 'sponsored'"
        )).scalar_one()
    assert sponsored == 1
