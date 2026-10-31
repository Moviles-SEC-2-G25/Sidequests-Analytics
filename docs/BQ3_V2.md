# BQ3 v2 — implementation and validation notes

Question: At which step of initial preference setup do users most frequently
abandon the process, and how does completing each step relate to acceptance of
their first recommended Side-Quest?

This version answers both parts for **Kotlin's four-step setup**. It does not
reinterpret legacy Sprint 2 completions as impressions or rejected recommendations.
Historical onboarding before instrumentation cannot be reconstructed. For the
initial-user demonstration, use newly created test accounts. Flutter needs a
compatible instrumented flow before it can be included; the v2 extraction is
explicitly scoped to `platform=kotlin`.

## Contract

Every BQ3 event has `metadata.bq_key=BQ3`, `schema_version=2`, `platform=kotlin`,
`event_id` (stable delivery UUID), `onboarding_id` (persistent journey UUID),
`event_sequence` (positive increasing integer), `completed_steps` (1-based),
and `onboarding_status`. `session_id` equals `onboarding_id`. `occurred_at` is
the original UTC client timestamp, preserved by the offline outbox. Device time
must be correct; timestamps from the future are excluded until they become valid.
No image contents, local file paths, credentials or preference selections are
included in BQ3 events.

| Event | Trigger / fields |
| --- | --- |
| `onboarding_started` | First setup recorded for this account on this installation. |
| `onboarding_resumed` | An unfinished journey is restored; refreshes its last activity. |
| `onboarding_step_viewed` | A step is first entered; `step_order`, `step_name`. |
| `onboarding_step_completed` | Continue / Start Exploring, including unchanged defaults; same step fields. |
| `onboarding_skipped` | Explicit Skip at current step; previous completions stay completed. |
| `onboarding_completed` | All four steps completed. |
| `onboarding_first_recommendation_shown` | First Smart Picks card composed after loading finishes; `exposure_id`, `quest_id`, `first_quest_id`. |
| `onboarding_first_recommendation_accepted` | Explicitly accept that same quest from Smart Picks as a new attempt; same exposure, plus `attempt_id`. |

Canonical steps: 1 interests, 2 difficulty, 3 typical_time, 4 budget_social.
An exposure is the first recommended **quest**, not the first recommendation batch.
Refreshing or reopening does not replace it. Catalogue acceptance, another quest,
resuming an existing attempt and repeated taps do not count as first acceptance.
Acceptance measures the explicit user action; check the owned backend attempt
separately with `BQ3_V2_VALIDATION.sql` to confirm successful lifecycle persistence.

## Computation

1. SQL extracts v2 Kotlin events from `public.analytics_events` without truncating
   old starts. Python deduplicates stable event IDs within user and journey.
2. Select each user's earliest instrumented start. Include starts within the last
   30 days; reinstalling or reopening is not another initial user in the result.
3. Count unique journeys viewing and completing each step. Explicit Skip marks
   the unfinished current step as a drop-off. An unfinished journey with no
   interaction for 24 hours is an inferred inactivity drop-off at its last viewed
   unfinished step. A recent unfinished journey stays pending. Returning later
   can reclassify an inferred drop-off; an app close alone is not proof of exit.
4. Step drop-off rate = (explicit skips + inferred drop-offs) /
   (step completions + explicit skips + inferred drop-offs). Pending journeys are
   shown separately and excluded from this resolved-step denominator.
5. Freeze completions at the first exposure. For each step compare completers
   versus non-completers **among users who saw a first recommendation**. A user
   who never saw one is excluded from both acceptance denominators.
6. Use a fixed 24-hour acceptance horizon after exposure. Include only exposures
   whose entire horizon has elapsed, even if a newer exposure was already accepted.
   Match acceptance by user, journey, exposure ID and quest ID, after exposure and
   within its horizon. Repeated deliveries count once. Report denominators, pending
   outcomes, accepted counts, rates and their difference in percentage points.

These comparisons are observational associations, not causal estimates of the
effect of completing a step. A missing comparison group produces null, not 0%.

## Run

Normal pipeline: `python -m sidequests_analytics.pipeline --job bq3` with `src`
on PYTHONPATH and server-side `DATABASE_URL`. It stores `analytics.bq_results`.
There is no new Supabase migration; existing analytics schema and photo migration
009 are required. No new schedule is deployed by these changes.

On Lex's computer, from this repository:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-bq3-local.ps1 -ReadOnly
```

The helper validates the Session pooler hostname and resolves DNS before asking
for a database password. Paste only the URI, without quotes or a `psql` command;
leave the literal `[YOUR-PASSWORD]` placeholder in place. Invalid hostnames,
embedded passwords and server overrides in the query string are rejected without
echoing the input. A DNS failure happens before authentication or any BQ3 query.

The helper asks locally for the Connect URI **with [YOUR-PASSWORD]** and the raw
database password separately. It handles `/`, `@`, `%` and other password symbols
without manual percent encoding. Do not put real credentials in commands or Git.

For a clearly labelled fast demonstration, use a fixed five-minute horizon and
wait until each first exposure is at least five minutes old, then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-bq3-local.ps1 -ObservationHours 0.0833333333333333 -Dashboard
```

This stores a **five-minute test horizon**, visibly recorded in every result and the
dashboard. It is not the production 24-hour analysis. Open http://127.0.0.1:8501
and keep the console open. Rerun with the default 24 hours for the normal snapshot.
If no v2 cohort exists, the helper stops without overwriting the previous BQ3.
The initial one-minute live test correctly reported zero acceptances: case A
accepted after 72.04 seconds. The subsequent five-minute demo uses a different
explicit window and must not be presented as the same metric or a 24-hour result.
If a dashboard is already running, stop it with Ctrl+C before starting another
instance on port 8501.

## Manual validation plan and status

- Case A (verified in Supabase): four completed steps and an exactly linked first acceptance.
- Case B (verified in Supabase): explicit skip at step 1, first exposure and no acceptance.
- Optional fresh account C: finish only step 1, skip step 2, see and accept the first card.
- Optional fresh account D: stop at step 3, close the app and leave it inactive past the
  chosen horizon. Compute the inactivity snapshot **before reopening D**. Then
  reopen it to verify that the same setup resumes and its recent activity changes
  the inferred inactive classification back to pending.
- Refresh a list: no second first-exposure event. Accept a different quest or use
  the catalogue: no first-recommendation acceptance event.
- Run the read-only SQL checks, run Python and inspect the saved v2 snapshot and
  dashboard. Preserve screenshots with horizon and counts visible.

Automated tests use synthetic fixtures, including the SQL extraction through a
fixture database and the actual Streamlit entry point. They do not establish that
real Android events have reached the shared Supabase instance.
