# BQ12 dashboard in Supabase

How to chart BQ12 (sponsored quest performance) inside the Supabase dashboard,
from chart-ready views over the stored BQ12 result. Metric definitions are in
[BUSINESS_QUESTIONS.md](BUSINESS_QUESTIONS.md#bq12--sponsored-quest-performance-sprint-4).

## What Supabase can chart today (checked 2026-11-24)

| Feature | What it does | Source |
| --- | --- | --- |
| SQL Editor charts | After running a query, plot the result choosing which columns are the axes. The Y axis must be numeric. | [Changelog, Mar 2024](https://supabase.com/changelog/21732-dashboard-weekly-updates-26-02-24-04-03-24), [fixes, Jan 2025](https://supabase.com/changelog/33144-dashboard-updates-13-01-25-27-01-25) |
| Explorer (Feature Preview) | Replaces the SQL Editor in the sidebar when turned on under **Feature Previews**. Each query cell renders as a table or a chart; Notebooks save the queries, not the results. | [Explorer and Notebooks, Oct 2026](https://supabase.com/blog/explorer-and-notebooks-investigations-your-team-can-rerun) |
| Multi-series bars/lines | Bar and line charts with an X axis and **up to 3 Y columns** ("Select up to 3 columns"), log scale for a single series. | [supabase/supabase#49241, merged Aug 2026](https://github.com/supabase/supabase/pull/49241) |
| Custom reports | Blocks that run a snippet saved in the SQL Editor and show it as a table or a chart; blocks can be resized and reordered. | [Studio updates, Apr 2025](https://supabase.com/blog/tabs-dashboard-updates) |

Not available natively: **heatmaps**, a "series"/group-by column (one Y column
per series instead, which is why the views below are pivoted), and running the
Python job on a schedule. Studio labels change between versions. The click path
below is the one the team already used for the BQ5 dashboard
(Sidequests-Flutter `docs/analytics/BQ5_DASHBOARD.md`); Supabase's public docs
don't spell out the custom-report menus.

## Steps

1. **Apply Sidequests-Backend migration 010** to the shared project (SQL Editor:
   paste `supabase/migrations/010_bq12_sponsored_quests.sql`, run; or
   `supabase db push` from the Backend repo if it is linked).
2. **Store a BQ12 result** with the pipeline, from this repo, with the
   server-side `DATABASE_URL` (Supabase pooler connection string, never in a
   client):

   ```powershell
   $env:PYTHONPATH = "src"
   python -m sidequests_analytics.pipeline --job bq12
   ```

   It writes `BQ12` and `BQ12_WEEKLY` rows to `analytics.bq_results`.
3. **Create the views:** **SQL Editor → New query**, paste the whole
   [BQ12_SUPABASE_VIEWS.sql](BQ12_SUPABASE_VIEWS.sql), **Run**. It is safe to run
   again. Check it with `select * from analytics.bq12_overall;` (2 rows).
4. **One snippet per chart:** for each row of the table below, **SQL Editor → New
   query**, paste the query, **Run**, rename the snippet (`BQ12-a Global`,
   `BQ12-b Business category`, `BQ12-c Interest`, `BQ12-d Category x interest`,
   `BQ12-e Weekly`), save it and move it to the project's shared folder so the
   team sees it.
5. **Reports → New custom report** named `BQ12 Dashboard`, then **Add block → SQL
   snippet** for each of the five snippets, shown as the chart type and with the
   X/Y columns of the table below.
   If your plan or Studio version doesn't offer custom reports, open each saved
   snippet, **Run** and switch the result to the **Chart** view. With Explorer
   turned on (**Feature Previews**), the same queries work as one cell per chart
   in a Notebook.
6. **Refresh:** the views always read the latest stored result, so re-running
   step 2 updates every chart. `computed_at` is in every view. Unlike BQ5's
   snippets, which query `analytics_events` live, BQ12 charts the versioned
   pipeline result, so the dashboard, Streamlit and the stored history show the
   same numbers with the same sample thresholds.

## Charts

| View | Query | Chart | X | Y | Decision it informs |
| --- | --- | --- | --- | --- | --- |
| (a) `bq12_overall` | `select * from analytics.bq12_overall` | Grouped bars | `sponsor_type` | `acceptance_rate_pct`, `completion_rate_pct` | Guardrail: does sponsored content hold up against ordinary content? If its completion falls clearly behind, tighten which sponsored quests are shown before selling more. |
| (b) `bq12_by_business_category` | `select * from analytics.bq12_by_business_category` | Grouped bars | `business_category` | `acceptance_rate_pct`, `completion_rate_pct` | Which sponsor types to prospect and how to price them; the `none` bar is the baseline. Categories without exposure appear with no bar. |
| (c) `bq12_by_interest` | `select * from analytics.bq12_by_interest` | Grouped bars (two charts) | `interest` | `sponsored_acceptance_rate_pct`, `non_sponsored_acceptance_rate_pct` (second chart: the two completion columns) | Which student audiences respond to sponsored quests: the audience pitch per sponsor. |
| (d) `bq12_by_category_interest` | `select segment_label, acceptance_rate_vs_non_sponsored_pp, completion_rate_vs_non_sponsored_pp from analytics.bq12_by_category_interest where sponsor_type = 'sponsored' and acceptance_sample_ok` | Bars (Supabase) / **heatmap** in Streamlit | `segment_label` | `acceptance_rate_vs_non_sponsored_pp`, `completion_rate_vs_non_sponsored_pp` | Targeting: which sponsor category to show to which interest, i.e. what "fits the user's context" should mean for sponsored quests. |
| (e) `bq12_weekly_trend` | `select * from analytics.bq12_weekly_trend` | Line | `week_start` | `sponsored_acceptance_rate_pct`, `non_sponsored_acceptance_rate_pct` (second chart: completion) | Whether sponsored performance holds as more sponsors join (fatigue), and the effect of a campaign week by week. The current week's completion is provisional. |

The heatmap of (d) — interest on X, business category on Y, colour = acceptance —
exists only in the Streamlit dashboard (`streamlit run dashboard_app.py`), which
also shows the interest-match table and the activity-category comparison.

Empty rates are `null`: the group had no exposure or fewer than 10 impressions /
5 accepted attempts. The views never turn them into 0 %; the count columns
(`impressions`, `accepted_attempts`, `*_impressions`, `*_attempts`) say how big
each group is. Interest rows don't add up to the total: a user counts once per
declared interest.

## Permissions

- The views contain only aggregated counts and rates: no user id, no event, no
  person's interests.
- They are `security_invoker` views, so they run with the reader's privileges,
  and `select` is revoked from `public`, `anon` and `authenticated`. The
  `analytics` schema has no grants for those roles (migration 005), and it is not
  one of the schemas exposed through the Data API: keep it out of the exposed
  schemas list so the views are never reachable with the publishable key.
- The SQL Editor reads them as the database owner. An external tool must use its
  own read-only role, never the service-role key or the `postgres` password:

  ```sql
  create role bq_dashboard_reader login password '<set in the tool, never in git>';
  grant usage on schema analytics to bq_dashboard_reader;
  grant select on analytics.bq_results to bq_dashboard_reader; -- read by the views
  grant select on
      analytics.bq12_overall, analytics.bq12_by_business_category,
      analytics.bq12_by_interest, analytics.bq12_by_category_interest,
      analytics.bq12_weekly_trend
  to bq_dashboard_reader;
  ```

## Alternatives when Supabase isn't enough

- **Streamlit (already in this repo):** every BQ12 chart including the heatmap,
  reading the same `analytics.bq_results`.
- **Metabase or Grafana:** connect to the Supabase Postgres connection string with
  `bq_dashboard_reader` and SSL, then build the same five charts from the same
  views; both draw heatmaps (Grafana's heatmap / Metabase's pivot table with
  conditional formatting) and can refresh on a schedule.
