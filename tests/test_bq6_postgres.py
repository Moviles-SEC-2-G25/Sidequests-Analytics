"""Runs BQ6 for real: the query uses PostgreSQL's jsonb operators, lateral joins
and `nulls last`, which SQLite can't run. A throwaway cluster is created in a
temporary folder with initdb. It never uses DATABASE_URL, the machine's running
PostgreSQL service or Supabase.
"""

import glob
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sidequests_analytics.pipeline import compute_bq6_base

SCHEMA = """
create table public.quests (
  id text primary key,
  duration_minutes integer not null,
  estimated_cost numeric(10,2) not null default 0
);
create table public.user_quests (
  id uuid primary key,
  user_id uuid not null,
  quest_id text not null references public.quests(id),
  status text not null,
  abandon_reason text,
  abandoned_at timestamptz
);
create table public.analytics_events (
  id bigint generated always as identity primary key,
  user_id uuid not null,
  event_type text not null,
  quest_id text,
  occurred_at timestamptz not null default now(),
  distance_meters integer,
  metadata jsonb not null default '{}'::jsonb
);
"""

USER = "00000000-0000-0000-0000-00000000000a"
OTHER_USER = "00000000-0000-0000-0000-00000000000b"
VALIDATION_SQL = Path(__file__).parent.parent / "docs" / "BQ6_ALTERNATIVES_VALIDATION.sql"


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
        message = "PostgreSQL no encontrado; instala PostgreSQL para correr los tests de BQ6"
        # On a developer's machine that's a skip; CI must really run this test.
        if os.getenv("CI"):
            pytest.fail(message)
        pytest.skip(message)

    data = tmp_path_factory.mktemp("bq6_cluster") / "data"
    port = _free_port()
    subprocess.run(
        [binaries / "initdb", "-D", data, "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C"],
        check=True,
        capture_output=True,
    )
    # In the file, not on the command line: Windows and Linux quote differently.
    with open(data / "postgresql.conf", "a", encoding="utf-8") as settings:
        settings.write(f"\nport = {port}\nlisten_addresses = '127.0.0.1'\nunix_socket_directories = ''\n")
    # Not captured: the server inherits the pipes and would never let them close.
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
        connection.execute(text("truncate public.analytics_events, public.user_quests, public.quests cascade"))
        connection.execute(text("insert into public.quests values ('walk', 30, 0)"))
    return engine


_attempts = 0


def _abandon(db, reason, *, event=None, user=USER, quest="walk", status="abandoned", abandoned_at="2026-10-01T10:00:00Z"):
    """An attempt in user_quests, optionally with its quest_abandoned event."""
    global _attempts
    _attempts += 1
    attempt = f"00000000-0000-0000-0001-{_attempts:012d}"
    with db.begin() as connection:
        connection.execute(
            text(
                "insert into public.user_quests (id, user_id, quest_id, status, abandon_reason, abandoned_at) "
                "values (:id, :user, :quest, :status, :reason, :abandoned_at)"
            ),
            {"id": attempt, "user": user, "quest": quest, "status": status, "reason": reason, "abandoned_at": abandoned_at},
        )
    if event is not None:
        _event(db, attempt, event, user=user, quest=quest)
    return attempt


def _event(db, attempt, event, user=USER, quest="walk"):
    metadata = dict(event.get("metadata", {}))
    if event.get("with_attempt_id", True):
        metadata["attempt_id"] = attempt
    with db.begin() as connection:
        connection.execute(
            text(
                "insert into public.analytics_events (user_id, event_type, quest_id, occurred_at, distance_meters, metadata) "
                "values (:user, :type, :quest, :occurred_at, :distance, cast(:metadata as jsonb))"
            ),
            {
                "user": user,
                "type": event.get("type", "quest_abandoned"),
                "quest": quest,
                "occurred_at": event.get("occurred_at", "2026-10-01T10:00:00Z"),
                "distance": event.get("distance_meters"),
                "metadata": json.dumps(metadata),
            },
        )


def _kotlin(reason, band, meters=644, **extra):
    """What Kotlin's AppViewModel.startAnotherQuest sends."""
    return {
        "distance_meters": meters,
        "metadata": {"schema_version": 1, "reason_code": reason, "quest_distance_band": band},
        **extra,
    }


def _flutter(reason, band, meters=850, **extra):
    """What the new Flutter client sends."""
    return {
        "distance_meters": meters,
        "metadata": {
            "schema_version": 1,
            "reason_code": reason,
            "quest_distance_band": band,
            "quest_distance_source": "gps",
            "platform": "flutter",
        },
        **extra,
    }


def _old_flutter(reason, meters):
    """What Flutter sent before this contract: no attempt_id, band or platform."""
    return {
        "distance_meters": meters,
        "with_attempt_id": False,
        "metadata": {"reason": reason, "step": 1, "completed_steps": 1},
    }


def _totals(rows, *keys):
    totals = {}
    for row in rows:
        key = tuple(row[name] for name in keys)
        totals[key] = totals.get(key, 0) + row["abandoned_count"]
    return totals


def test_both_platforms_group_under_the_same_reason_and_band(db):
    _abandon(db, "too_far", event=_kotlin("too_far", "500_m_to_1_5_km"))
    _abandon(db, "too_far", event=_flutter("too_far", "500_m_to_1_5_km"))
    _abandon(db, "ran_out_of_time", event=_kotlin("ran_out_of_time", "location_independent", meters=None))
    _abandon(db, "ran_out_of_time", event=_flutter("ran_out_of_time", "location_independent", meters=None))

    rows = compute_bq6_base(db)

    assert _totals(rows, "abandon_reason", "distance_bucket") == {
        ("too_far", "500_m_to_1_5_km"): 2,
        ("ran_out_of_time", "location_independent"): 2,
    }
    assert _totals(rows, "abandon_reason", "distance_bucket", "platform") == {
        ("too_far", "500_m_to_1_5_km", "kotlin"): 1,
        ("too_far", "500_m_to_1_5_km", "flutter"): 1,
        ("ran_out_of_time", "location_independent", "kotlin"): 1,
        ("ran_out_of_time", "location_independent", "flutter"): 1,
    }


def test_distance_source_says_how_each_platform_measured(db):
    _abandon(db, "too_far", event=_kotlin("too_far", "over_1_5_km"))
    _abandon(db, "too_far", event=_flutter("too_far", "over_1_5_km"))

    rows = compute_bq6_base(db)

    assert _totals(rows, "platform", "distance_source") == {("kotlin", "catalogue"): 1, ("flutter", "gps"): 1}


def test_distance_source_comes_from_the_event_before_being_inferred(db):
    event = {"metadata": {"quest_distance_band": "under_500_m", "quest_distance_source": "gps"}}
    _abandon(db, "too_far", event=event)  # no platform to infer it from

    row = compute_bq6_base(db)[0]

    assert (row["platform"], row["distance_source"]) == ("unknown", "gps")


def test_kotlin_only_on_campus_band_passes_through(db):
    _abandon(db, "other", event=_kotlin("other", "on_campus", meters=None))

    assert _totals(compute_bq6_base(db), "distance_bucket") == {("on_campus",): 1}


@pytest.mark.parametrize(
    "old, new",
    [
        ("place_closed", "place_unavailable"),
        ("too_hard", "too_difficult"),
        ("bad_weather", "weather_or_mood_changed"),
        ("lost_interest", "other"),
        ("not_specified", "other"),
    ],
)
def test_old_flutter_codes_count_with_kotlin_codes(db, old, new):
    _abandon(db, old)
    _abandon(db, new)

    assert _totals(compute_bq6_base(db), "abandon_reason") == {(new,): 2}


def test_null_reason_stays_unspecified_and_unknown_text_is_kept(db):
    _abandon(db, None)
    _abandon(db, "lluvia")

    assert _totals(compute_bq6_base(db), "abandon_reason") == {("Unspecified",): 1, ("lluvia",): 1}


@pytest.mark.parametrize(
    "meters, bucket",
    [
        (499, "legacy_gps_under_500_m"),
        (500, "legacy_gps_500_m_to_2_km"),
        (1999, "legacy_gps_500_m_to_2_km"),
        (2000, "legacy_gps_2_km_to_10_km"),
        (9999, "legacy_gps_2_km_to_10_km"),
        (10000, "legacy_gps_over_10_km"),
        (None, "unknown"),
    ],
)
def test_old_flutter_events_get_legacy_buckets_never_mixed_with_bands(db, meters, bucket):
    _abandon(db, "too_far", event=_old_flutter("too_far", meters))

    row = compute_bq6_base(db)[0]

    assert row["distance_bucket"] == bucket
    assert row["platform"] == "flutter"
    assert row["distance_source"] == "gps"


def test_abandonment_without_an_event_is_unknown(db):
    _abandon(db, "other")

    row = compute_bq6_base(db)[0]

    assert (row["distance_bucket"], row["platform"], row["distance_source"]) == ("unknown", "unknown", "unknown")


def test_links_by_attempt_id_even_when_another_event_is_closer_in_time(db):
    first = _abandon(db, "too_far", abandoned_at="2026-10-01T10:00:00Z")
    second = _abandon(db, "too_far", abandoned_at="2026-10-02T10:00:00Z")
    # Crossed on purpose: by time alone, each attempt would take the other's band.
    _event(db, first, _flutter("too_far", "under_500_m", occurred_at="2026-10-02T10:00:00Z"))
    _event(db, second, _flutter("too_far", "over_1_5_km", occurred_at="2026-10-01T10:00:00Z"))

    assert _totals(compute_bq6_base(db), "distance_bucket") == {("under_500_m",): 1, ("over_1_5_km",): 1}


def test_an_event_of_another_attempt_is_never_used(db):
    _abandon(db, "too_far", event=_flutter("too_far", "under_500_m"))
    _abandon(db, "too_far")  # same user and quest, but no event of its own

    assert _totals(compute_bq6_base(db), "distance_bucket") == {("under_500_m",): 1, ("unknown",): 1}


def test_old_events_fall_back_to_the_closest_in_time(db):
    _abandon(db, "too_far", abandoned_at="2026-10-01T10:00:00Z")
    far = _old_flutter("too_far", 300)
    close = _old_flutter("too_far", 5000)
    with db.connect() as connection:
        attempt = connection.execute(text("select id from public.user_quests")).scalar()
    # The closest goes in first: the newest row must not win just for being newer.
    _event(db, attempt, {**close, "occurred_at": "2026-10-01T10:00:05Z"})
    _event(db, attempt, {**far, "occurred_at": "2026-09-01T10:00:00Z"})

    assert _totals(compute_bq6_base(db), "distance_bucket") == {("legacy_gps_2_km_to_10_km",): 1}


def test_abandoned_at_missing_still_links_the_event(db):
    _abandon(db, "too_far", event=_old_flutter("too_far", 300), abandoned_at=None)

    assert _totals(compute_bq6_base(db), "distance_bucket") == {("legacy_gps_under_500_m",): 1}


def test_resumed_and_abandoned_again_uses_the_latest_event_of_that_attempt(db):
    attempt = _abandon(db, "too_far", abandoned_at="2026-10-01T10:00:00Z")
    _event(db, attempt, _flutter("ran_out_of_time", "under_500_m", occurred_at="2026-10-01T10:00:00Z"))
    _event(db, attempt, _flutter("too_far", "over_1_5_km", occurred_at="2026-10-05T10:00:00Z"))

    assert _totals(compute_bq6_base(db), "distance_bucket") == {("over_1_5_km",): 1}


def test_only_abandoned_attempts_of_the_same_user_count(db):
    _abandon(db, "too_far", status="completed")
    _abandon(db, "too_far", status="in_progress")
    # Another user's event for the same quest must not be picked up.
    attempt = _abandon(db, "too_far")
    _event(db, attempt, {**_flutter("too_far", "under_500_m"), "with_attempt_id": False}, user=OTHER_USER)

    assert _totals(compute_bq6_base(db), "distance_bucket") == {("unknown",): 1}


def test_alternatives_validation_query_runs_with_events_of_both_platforms(db):
    """docs/BQ6_ALTERNATIVES_VALIDATION.sql, the parametrized copy of Kotlin's."""
    sql = VALIDATION_SQL.read_text(encoding="utf-8").replace("00000000-0000-0000-0000-000000000000", USER)
    kotlin = _abandon(db, "too_far", event=_kotlin("too_far", "under_500_m"))
    flutter = _abandon(db, "too_far", event=_flutter("too_far", "under_500_m"))
    for attempt, platform in [(kotlin, None), (flutter, "flutter")]:
        metadata = {
            "algorithm_version": "lex_alternatives_v1",
            "source_quest_id": "walk",
            "source_attempt_id": attempt,
            "reason_code": "too_far",
            "context_source": "device",
            **({"platform": platform} if platform else {}),
        }
        _event(db, attempt, {"type": "quest_alternative_shown", "metadata": metadata, "with_attempt_id": False}, quest="walk")

    with db.connect() as connection:
        rows = connection.execute(text(sql)).mappings().all()

    assert {row["platform"] for row in rows} == {"kotlin", "flutter"}
    assert all(row["linked_abandonment_event"] for row in rows)
    assert all(row["source_attempt_status"] == "abandoned" for row in rows)
