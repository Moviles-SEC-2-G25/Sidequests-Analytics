import argparse
import json
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from .db import get_engine
from .bq3 import summarize_bq3
from .queries import (
    BQ1_MODULE_FAILURES_AFTER_RESUME_SQL,
    BQ2_GROUP_CHALLENGES_SQL,
    BQ3_ONBOARDING_DROPOFF_SQL,
    BQ4_INSTANT_PLAN_SQL,
    BQ5_PERSONALIZED_RECOMMENDATION_SQL,
    BQ6_ABANDONMENT_BASE_SQL,
    BQ7_GROUP_VS_INDIVIDUAL_QUESTS_SQL,
    BQ8_RECOMMENDATION_DIVERSITY_SQL,
    BQ8_EXPERIENCED_COHORT_SQL,
    BQ9_CATEGORY_PERFORMANCE_SQL,
    BQ10_LOCATION_INDEPENDENT_USAGE_SQL,
    BQ12_SPONSORED_PERFORMANCE_SQL,
    BQ12_WEEKLY_TREND_SQL,
    USER_FEATURES_SQL,
)

# BQ12 defaults: a rate needs at least this many impressions / accepted attempts.
BQ12_WINDOW_DAYS = 30
BQ12_MIN_IMPRESSIONS = 10
BQ12_MIN_ATTEMPTS = 5
BQ12_TREND_WEEKS = 12


def _records(df: pd.DataFrame) -> list[dict]:
    clean = df.where(pd.notnull(df), None)
    return clean.to_dict(orient="records")


def _json_records(df: pd.DataFrame) -> list[dict]:
    # A float column keeps NaN through `where`; NaN isn't valid JSON for jsonb.
    return df.astype(object).where(pd.notnull(df), None).to_dict(orient="records")


def compute_bq1(engine) -> list[dict]:
    return _records(pd.read_sql(text(BQ1_MODULE_FAILURES_AFTER_RESUME_SQL), engine))


def bq2_schema_ready(engine) -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(text(
            "select to_regclass('sidequests_group_private.operations') is not null"
        )).scalar())


def compute_bq2(engine) -> list[dict]:
    frame = pd.read_sql(text(BQ2_GROUP_CHALLENGES_SQL), engine)
    return frame.astype(object).where(pd.notnull(frame), None).to_dict(orient="records")


def compute_bq3(engine, observation_hours=24.0, as_of=None) -> list[dict]:
    records = pd.read_sql(text(BQ3_ONBOARDING_DROPOFF_SQL), engine).to_dict(orient="records")
    return summarize_bq3(records, observation_hours=observation_hours, as_of=as_of)


def compute_bq4(engine) -> list[dict]:
    return _records(pd.read_sql(text(BQ4_INSTANT_PLAN_SQL), engine))


def compute_bq7(engine) -> list[dict]:
    return _records(pd.read_sql(text(BQ7_GROUP_VS_INDIVIDUAL_QUESTS_SQL), engine))


def compute_bq8(engine) -> list[dict]:
    return _records(pd.read_sql(text(BQ8_RECOMMENDATION_DIVERSITY_SQL), engine))


def compute_bq8_experienced(engine) -> list[dict]:
    """BQ8 original cohort, filtered to users with >=2 previous completions."""
    frame = pd.read_sql(text(BQ8_EXPERIENCED_COHORT_SQL), engine)
    # Numeric NaN must become JSON null; pandas numeric columns otherwise retain NaN.
    return frame.astype(object).where(pd.notnull(frame), None).to_dict(orient="records")


def compute_bq9(engine) -> list[dict]:
    return _records(pd.read_sql(text(BQ9_CATEGORY_PERFORMANCE_SQL), engine))


def compute_bq5(engine) -> list[dict]:
    return _records(pd.read_sql(text(BQ5_PERSONALIZED_RECOMMENDATION_SQL), engine))


def compute_bq6_base(engine) -> list[dict]:
    return _records(pd.read_sql(text(BQ6_ABANDONMENT_BASE_SQL), engine))


def compute_bq10(engine) -> list[dict]:
    return _records(pd.read_sql(text(BQ10_LOCATION_INDEPENDENT_USAGE_SQL), engine))


def compute_bq12(
    engine,
    window_days: int = BQ12_WINDOW_DAYS,
    min_impressions: int = BQ12_MIN_IMPRESSIONS,
    min_attempts: int = BQ12_MIN_ATTEMPTS,
) -> list[dict]:
    """Sponsored vs non-sponsored acceptance and completion, one row per segment."""
    frame = pd.read_sql(
        text(BQ12_SPONSORED_PERFORMANCE_SQL),
        engine,
        params={
            "window_days": window_days,
            "min_impressions": min_impressions,
            "min_attempts": min_attempts,
        },
    )
    return _json_records(frame)


def compute_bq12_weekly(
    engine,
    trend_weeks: int = BQ12_TREND_WEEKS,
    min_impressions: int = BQ12_MIN_IMPRESSIONS,
    min_attempts: int = BQ12_MIN_ATTEMPTS,
) -> list[dict]:
    """BQ12 per week and sponsor type, for the trend chart."""
    frame = pd.read_sql(
        text(BQ12_WEEKLY_TREND_SQL),
        engine,
        params={
            "trend_weeks": trend_weeks,
            "min_impressions": min_impressions,
            "min_attempts": min_attempts,
        },
    )
    return _json_records(frame)


def refresh_user_features(engine) -> int:
    df = pd.read_sql(text(USER_FEATURES_SQL), engine)
    if df.empty:
        return 0

    statement = text(
        """
        insert into analytics.user_features (
            user_id,
            preferred_categories,
            avg_completed_duration_minutes,
            completion_rate,
            last_computed_at
        )
        values (
            :user_id,
            :preferred_categories,
            :avg_completed_duration_minutes,
            :completion_rate,
            now()
        )
        on conflict (user_id) do update set
            preferred_categories = excluded.preferred_categories,
            avg_completed_duration_minutes = excluded.avg_completed_duration_minutes,
            completion_rate = excluded.completion_rate,
            last_computed_at = now()
        """
    )

    with engine.begin() as conn:
        conn.execute(statement, _records(df))

    return len(df)


def store_bq_result(engine, bq_key: str, payload: list[dict]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                insert into analytics.bq_results (bq_key, payload)
                values (:bq_key, cast(:payload as jsonb))
                """
            ),
            {
                "bq_key": bq_key,
                "payload": json.dumps(
                    {
                        "computed_at": datetime.now(timezone.utc).isoformat(),
                        "rows": payload,
                    },
                    default=str,
                ),
            },
        )


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bq3-observation-hours", type=float, default=24.0,
                        help="BQ3 inactivity and first-acceptance horizon (default: 24 hours)")
    parser.add_argument(
        "--job",
        choices=("all", "bq1", "bq2", "bq3", "bq4", "bq5", "bq6", "bq7", "bq8", "bq9", "bq10", "bq12", "features"),
        default="all",
    )
    parser.add_argument("--bq12-window-days", type=int, default=BQ12_WINDOW_DAYS,
                        help="BQ12 window (default: 30 days)")
    parser.add_argument("--bq12-min-impressions", type=int, default=BQ12_MIN_IMPRESSIONS,
                        help="BQ12: fewer impressions than this leave the acceptance rate null (default: 10)")
    parser.add_argument("--bq12-min-attempts", type=int, default=BQ12_MIN_ATTEMPTS,
                        help="BQ12: fewer accepted attempts than this leave the completion rate null (default: 5)")
    parser.add_argument("--bq12-trend-weeks", type=int, default=BQ12_TREND_WEEKS,
                        help="BQ12_WEEKLY: weeks in the trend, current week included (default: 12)")
    args = parser.parse_args()

    engine = get_engine()

    if args.job in ("all", "features"):
        refreshed = refresh_user_features(engine)
        print(f"refreshed user_features: {refreshed}")

    if args.job in ("all", "bq1"):
        bq1 = compute_bq1(engine)
        store_bq_result(engine, "BQ1", bq1)
        print(f"stored BQ1 rows: {len(bq1)}")

    if args.job in ("all", "bq2"):
        if bq2_schema_ready(engine):
            bq2 = compute_bq2(engine)
            store_bq_result(engine, "BQ2", bq2)
            print(f"stored BQ2 rows: {len(bq2)}")
        elif args.job == "bq2":
            raise RuntimeError("BQ2 backend migration has not been applied.")
        else:
            print("skipped BQ2: backend migration not installed")

    if args.job in ("all", "bq3"):
        bq3 = compute_bq3(engine, observation_hours=args.bq3_observation_hours)
        store_bq_result(engine, "BQ3", bq3)
        print(f"stored BQ3 rows: {len(bq3)}")

    if args.job in ("all", "bq4"):
        bq4 = compute_bq4(engine)
        store_bq_result(engine, "BQ4", bq4)
        print(f"stored BQ4 rows: {len(bq4)}")

    if args.job in ("all", "bq5"):
        bq5 = compute_bq5(engine)
        store_bq_result(engine, "BQ5", bq5)
        print(f"stored BQ5 rows: {len(bq5)}")

    if args.job in ("all", "bq6"):
        bq6 = compute_bq6_base(engine)
        store_bq_result(engine, "BQ6", bq6)
        print(f"stored BQ6 rows: {len(bq6)}")


    if args.job in ("all", "bq7"):
        bq7 = compute_bq7(engine)
        store_bq_result(engine, "BQ7", bq7)
        print(f"stored BQ7 rows: {len(bq7)}")

    if args.job in ("all", "bq8"):
        bq8 = compute_bq8(engine)
        store_bq_result(engine, "BQ8", bq8)
        print(f"stored BQ8 rows: {len(bq8)}")
        experienced = compute_bq8_experienced(engine)
        store_bq_result(engine, "BQ8_EXPERIENCED", experienced)
        print(f"stored BQ8_EXPERIENCED rows: {len(experienced)}")

    if args.job in ("all", "bq9"):
        bq9 = compute_bq9(engine)
        store_bq_result(engine, "BQ9", bq9)
        print(f"stored BQ9 rows: {len(bq9)}")

    if args.job in ("all", "bq10"):
        bq10 = compute_bq10(engine)
        store_bq_result(engine, "BQ10", bq10)
        print(f"stored BQ10 rows: {len(bq10)}")

    if args.job in ("all", "bq12"):
        bq12 = compute_bq12(
            engine,
            window_days=args.bq12_window_days,
            min_impressions=args.bq12_min_impressions,
            min_attempts=args.bq12_min_attempts,
        )
        store_bq_result(engine, "BQ12", bq12)
        print(f"stored BQ12 rows: {len(bq12)}")
        weekly = compute_bq12_weekly(
            engine,
            trend_weeks=args.bq12_trend_weeks,
            min_impressions=args.bq12_min_impressions,
            min_attempts=args.bq12_min_attempts,
        )
        store_bq_result(engine, "BQ12_WEEKLY", weekly)
        print(f"stored BQ12_WEEKLY rows: {len(weekly)}")


if __name__ == "__main__":
    run()
