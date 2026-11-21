# BQ8 Sprint 4 — Experienced-user recommendation diversity

**Selected by Sebastián (Kotlin subgroup).** The client-side experiment uses the
shared `recommend_quests` RPC: server-assigned `control` and `diverse` arms,
not the optional local "Something Different" browsing view.

## Original research question and measurable proxy

Does increasing recommendation category diversity relate to the acceptance
and return rates of users who have *already completed multiple quests*?

The existing `BQ8` weekly result covers every instrumented user and contains
a large `unassigned` legacy cohort. This Sprint 4 companion computes
`BQ8_EXPERIENCED` and does **not** overwrite that historical definition.

- **Who:** users with at least two `user_quests.status='completed'` attempts
  where `completed_at` is strictly earlier than the displayed recommendation.
  We chose *two* as a reproducible interpretation of "multiple."
- **Arms:** `control` vs `diverse`, copied from the server RPC. The assignment
  is account-stable, but it is not evidence of a randomized controlled trial.
- **Exposures:** deduplicate on user/session/batch/quest. Displayed lists with
  only one visible item do not enter the diversity average. Lists for the same
  user can be numerous; count distinct users separately.
- **Acceptance opportunity:** one exposed user/session/quest, matched to
  `recommendation_accepted` with the same user, session and quest, ordered after
  the impression and within the following 24 hours. Only opportunities that
  have completed 24 hours of observation enter acceptance-rate denominators.
  A duplicate replay of one impression is not an additional opportunity.
- **Return proxy:** at least one **different instrumented session** from
  30 minutes to 24 hours after the user's first eligible exposure. Only users
  whose first eligible exposure is at least 24 hours old enter the rate.
  **This does not measure all app opens or verified retention.**
- **Window:** last 30 days for exposure and user eligibility. This is a
  descriptive comparison, not causal evidence of an improvement.

## Exact implementation

- `src/sidequests_analytics/sql/bq8_experienced.sql`: read-only SQL.
- `src/sidequests_analytics/queries.py`: loads the SQL constant.
- `src/sidequests_analytics/pipeline.py`: computes the experienced result
  when running the existing `bq8` job, storing an additional
  `BQ8_EXPERIENCED` row; legacy BQ8 is preserved.
- `src/sidequests_analytics/dashboard.py`: displays cohort size, acceptance,
  24h return proxy and a small-sample warning.
- `scripts/run_bq8_local.py` and `scripts/run-bq8-local.ps1`: secure
  interactive PostgreSQL connection; read-only by default.
- `tests/test_queries.py`: tests expected cohort and maturity contracts.

## Windows PowerShell — same pattern as the earlier BQ3 command

1. Open a PowerShell terminal in the `Sidequests-Analytics` repository.
2. Checkout the *dedicated* BQ8 analytics branch:
   `git fetch origin; git switch feature/s4-bq8-experienced-analytics`.
3. Use the same Python environment used by previous Analytics exercises.
   The wrapper checks a sibling `analytics-venv` or an in-repo `.venv`.
   Ensure dependencies from `requirements.txt` are installed.
4. In the Supabase **Sidequests** project, open **Connect → Session pooler**.
   Copy the **PostgreSQL URI** retaining the literal `[YOUR-PASSWORD]`
   placeholder. It must point to the correct project and port 5432.
5. Execute:

   ```powershell
   .\scripts\run-bq8-local.ps1
   ```

   The runner hides the URI input and prompts separately for the **database
   password** (NOT a Supabase publishable/anon key). It executes SELECT queries,
   displays aggregate rows and makes **no changes to Supabase**.
6. When the team has reviewed the output and explicitly approves publication,
   use:

   ```powershell
   .\scripts\run-bq8-local.ps1 -Publish -Dashboard
   ```

   This **inserts new aggregated results** into `analytics.bq_results`, then
   opens the local dashboard at `http://127.0.0.1:8501`. It does not change
   user data or source events, but is a database write. Stop the server with
   Ctrl+C. Without `-Publish`, `-Dashboard` may show older saved results.

Do **not** copy the URI/password into issues, Wiki, pull requests, logs, images
or chat. A database password belongs only in the hidden local prompt.

## Read-only live check performed on 2026-11-21

The query in the dedicated SQL file was executed without writing to Supabase.
At that point the historical 30-day window yielded:

| Metric | Control | Diverse |
| --- | ---: | ---: |
| Experienced users | 2 | 1 |
| Comparable recommendation batches | 118 | 2 |
| Average distinct categories per comparable list | 2.56 | 3.00 |
| Mature acceptance opportunities | 159 | 6 |
| Observed accepts within 24h | 2 | 0 |
| Acceptance rate | 1.26% | 0.00% |
| Mature return users | 2 | 1 |
| Observed different-session return within 24h | 1 | 0 |

The large batch imbalance and only three eligible users make quantitative
treatment conclusions **unjustified**. These are historical cross-platform
events, **not** validation that our new Kotlin `rpc_viewport` events work.
Observed return does not prove next-day retention.

## Validation gates

- [x] SQL from the committed file executed successfully on live Supabase
      read-only and returned explicit control/diverse rows.
- [ ] Dedicated-branch Python CI and tests pass.
- [ ] Interactive PowerShell connection verified on the student's machine.
- [ ] Live new Kotlin viewport events confirmed from a real Android.
- [ ] A new result published to `analytics.bq_results` **only after approval**.
- [ ] Dashboard output verified with those published aggregates.
- [ ] Wiki screenshots are redacted and identify dates, versions, sample sizes.

The publication and phone evidence are still pending. Do not represent this
document as the graded final writeup; the subgroup should review it.
