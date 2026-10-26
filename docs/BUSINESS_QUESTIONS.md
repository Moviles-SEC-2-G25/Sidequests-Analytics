# Sprint 2 Business Questions

## BQ3 — Onboarding Drop-off
**Type 2**

Which onboarding step has the highest abandonment/drop-off rate?

## BQ4 — Instant Plan Adoption
**Type 2**

Does the "instant plan" quick-start path get users into a quest faster, and with fewer interactions, than the standard flow?

Computed from `metadata.start_path` (`instant_plan` | `standard`) on `recommendation_accepted`/`quest_started` events. BQ4 reports, per path: number of starts, average and median `seconds_to_start`, average `interactions_to_start`, and the percentage reduction of both versus the `standard` path. See `docs/EVENT_SCHEMA.md` for the event contract.

## BQ5 — Personalized Quest Recommendation
**Type 2**

Given the user's available time, preferred level of social interaction, interests, and previous quest interactions, which three available Sidequests have the highest relevance for the current session?

Runtime ranking is provided by the shared authenticated `public.recommend_quests` RPC. The analytics pipeline implements BQ5 evidence through `BQ5_PERSONALIZED_RECOMMENDATION_SQL`, which reads real `recommendation_shown` events and stores the latest top-three recommendation list per user/session in `analytics.bq_results`. This keeps the low-latency ranking in the backend while making BQ5 explicitly reproducible inside the analytics system.

## BQ6 — Quest Abandonment Reasons
**Type 2**

Which quest/context characteristics are most associated with users abandoning a quest?

## BQ8 — Recommendation Diversity
**Type 3**

How diverse are the recommendations shown to users over time?

Implemented as an experiment: `public.recommend_quests` assigns each user a
stable arm (`control` = BQ5 ranking, `diverse` = novelty + category-repeat
penalties). BQ8 reports, per variant and week: distinct categories per list,
normalised category entropy, catalogue coverage, repeat-exposure rate, and the
acceptance rate as a guardrail. See `docs/EVENT_SCHEMA.md` for the event contract.

## BQ9 — Quest Category Performance
**Type 3**

How do quest categories compare in acceptance/completion performance?

Computed per category over the last 30 days, as a two-stage funnel:

- **Acceptance** (from `analytics_events`): unique recommendation impressions
  (one per user + session + quest, so list reloads do not inflate it), how many
  were accepted and how many were skipped ("Not for me"). Accepts/skips are
  linked to the impression by `user_id` + `session_id` + `quest_id`, as in BQ8.
- **Completion** (from `user_quests`): every accepted attempt, whether it came
  from a recommendation or the catalogue, split into completed, abandoned and
  still open. Reports completion rate over all attempts, completion rate over
  resolved attempts only (completed / (completed + abandoned)), abandonment
  rate, median minutes from accept to complete, and average rating.

Each category also gets `acceptance_rate_vs_overall_pp` and
`completion_rate_vs_overall_pp`: the gap, in percentage points, against the
average of all categories. Rows are ordered best to worst by completion rate,
then acceptance rate. No extra event fields are required.

## BQ10 — Location-Independent Mode Usage
**Type 3**

How is location-independent mode used across sessions/context conditions?

## Rule

A BQ only counts for Sprint 2 when its logic is implemented and demonstrated against real analytics data; documentation alone is not sufficient.


## Sprint 3 — BQ12 Sponsored Quest Performance (Sebastián, Type 4)

**Original Sprint 1 question:** What is the acceptance and completion rate of sponsored Side-Quests compared with non-sponsored ones, segmented by business category and by the user's declared interests?

**Why:** The team's proposed revenue model includes sponsored quests. We need evidence of whether sponsorship changes recommendations' attractiveness or users' likelihood of completing activities, without degrading relevance for students.

**Current implemented computation (pending live validation):**
- The `bq12` analytics job calculates 30-day recommendation acceptance rates from de-duplicated `recommendation_shown` impressions and matching `quest_accepted` or `recommendation_accepted` events in the same session within one day of a recommendation.
- It separately calculates completion rates from accepted quest attempts (`user_quests`), including quests accepted from Explore rather than recommendations.
- Both metrics are grouped by sponsored versus ordinary quests, **quest activity category**, and declared-interest match (`matching`, `not_matching`, `none_declared`).
- Results are stored in `analytics.bq_results` with `bq_key = 'BQ12'`, using the existing Python pipeline.

**Limitations that MUST be resolved before marking the original BQ fully complete:**
1. The existing `quests.category` is an **activity category**, NOT the sponsor's business category. The backend must explicitly model/populate sponsor business category if the full original segmentation is required.
2. `user_preferences.interests` is the currently declared value, not a historical snapshot. The report must not claim interests were recorded at the time of the original interaction.
3. The repository includes only one sponsored quest in its sample seed, which is insufficient to draw robust business conclusions.
4. The pipeline is not yet demonstrated against hosted Supabase, nor is a Kotlin screen consuming the resulting analytics output. Documentation and CI cannot replace those demonstrations.

**How to reproduce when connected:** Run `python -m sidequests_analytics.pipeline --job bq12` in a trusted server environment with `DATABASE_URL`, then inspect the latest `analytics.bq_results` BQ12 payload. Never put `DATABASE_URL` or a service-role key into a mobile client.
