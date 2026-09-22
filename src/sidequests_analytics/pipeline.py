import argparse
import json
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from .db import get_engine
from .queries import (
    BQ6_ABANDONMENT_BASE_SQL,
    BQ9_CATEGORY_PERFORMANCE_SQL,
    USER_FEATURES_SQL,
)


def _records(df: pd.DataFrame) -> list[dict]:
    clean = df.where(pd.notnull(df), None)
    return clean.to_dict(orient="records")


def compute_bq9(engine) -> list[dict]:
    return _records(pd.read_sql(text(BQ9_CATEGORY_PERFORMANCE_SQL), engine))


def compute_bq6_base(engine) -> list[dict]:
    return _records(pd.read_sql(text(BQ6_ABANDONMENT_BASE_SQL), engine))


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
    parser.add_argument(
        "--job",
        choices=("all", "bq6", "bq9", "features"),
        default="all",
    )
    args = parser.parse_args()

    engine = get_engine()

    if args.job in ("all", "features"):
        refreshed = refresh_user_features(engine)
        print(f"refreshed user_features: {refreshed}")

    if args.job in ("all", "bq6"):
        bq6 = compute_bq6_base(engine)
        store_bq_result(engine, "BQ6", bq6)
        print(f"stored BQ6 rows: {len(bq6)}")

    if args.job in ("all", "bq9"):
        bq9 = compute_bq9(engine)
        store_bq_result(engine, "BQ9", bq9)
        print(f"stored BQ9 rows: {len(bq9)}")


if __name__ == "__main__":
    run()
