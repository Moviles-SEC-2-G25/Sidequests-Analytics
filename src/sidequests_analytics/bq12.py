"""BQ12 (Type 4): reshape the stored sponsored-performance rows for reading.

All metrics are computed in SQL (queries.BQ12_SPONSORED_PERFORMANCE_SQL); these
helpers only pick a segment level and pivot it for charts. A null rate means
"no exposure or below the sample threshold", never 0 %, and stays null here.
"""
import pandas as pd

SPONSOR_TYPES = ("sponsored", "non_sponsored")
RATE_COLUMNS = (
    "acceptance_rate_pct",
    "completion_rate_pct",
    "resolved_completion_rate_pct",
    "abandonment_rate_pct",
    "acceptance_rate_vs_non_sponsored_pp",
    "completion_rate_vs_non_sponsored_pp",
)


def bq12_level(rows: list[dict], level: str) -> pd.DataFrame:
    """The rows of one `segment_level`, with rates as numbers (None -> NaN)."""
    frame = pd.DataFrame(rows)
    if frame.empty or "segment_level" not in frame.columns:
        return pd.DataFrame()
    selected = frame[frame["segment_level"] == level].reset_index(drop=True)
    for column in RATE_COLUMNS:
        if column in selected.columns:
            selected[column] = pd.to_numeric(selected[column], errors="coerce")
    return selected


def bq12_compare(rows: list[dict], level: str, dimension: str, metric: str) -> pd.DataFrame:
    """One row per value of `dimension`, one column per sponsor type (grouped bars)."""
    selected = bq12_level(rows, level)
    if selected.empty:
        return pd.DataFrame()
    wide = selected.pivot(index=dimension, columns="sponsor_type", values=metric)
    return wide.reindex(columns=list(SPONSOR_TYPES)).astype(float)


def bq12_headline(rows: list[dict]) -> dict:
    """Overall sponsored vs non-sponsored comparison, the BQ12 answer in brief.

    Returns, per sponsor type, the overall row (rates None when not reportable),
    plus `comparable`: both sides have a reportable acceptance AND completion
    rate, so the gaps can be read at all.
    """
    overall = {
        row["sponsor_type"]: row
        for row in rows
        if row.get("segment_level") == "overall"
    }
    sponsored = overall.get("sponsored", {})
    non_sponsored = overall.get("non_sponsored", {})
    rates = ("acceptance_rate_pct", "completion_rate_pct")
    return {
        "sponsored": sponsored,
        "non_sponsored": non_sponsored,
        "acceptance_gap_pp": sponsored.get("acceptance_rate_vs_non_sponsored_pp"),
        "completion_gap_pp": sponsored.get("completion_rate_vs_non_sponsored_pp"),
        "comparable": all(
            side.get(rate) is not None for side in (sponsored, non_sponsored) for rate in rates
        ),
    }
