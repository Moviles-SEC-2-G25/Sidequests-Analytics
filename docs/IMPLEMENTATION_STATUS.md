# Analytics implementation status

## Implemented and validated

- Shared Supabase PostgreSQL database.
- Mobile event ingestion through `public.analytics_events`.
- Real Kotlin events validated in Supabase, including `recommendation_shown` and `recommendation_skipped`.
- Analytics output schema: `analytics`.
- `analytics.user_features`.
- `analytics.bq_results`.
- Python/SQLAlchemy analytics engine skeleton with automated CI tests.
- BQ9 query (Type 3): per-category funnel over the last 30 days —
  recommendation acceptance/skip rates from `recommendation_*` events, plus
  completion, abandonment, median time to complete and average rating from
  `user_quests`, each compared against the all-category average. Validated
  on 2026-10-01 against hosted Supabase with real Flutter-generated data
  (65 recommendation impressions, 20 quest attempts across 6 categories);
  per-category totals reconcile with the raw `user_quests` status counts.
- BQ6 base query: abandonment reason segmented by duration, cost and distance (bucket from the `quest_abandoned` event's `distance_meters`; Flutter emits it).
- BQ5 shared runtime recommender implemented as the authenticated PostgreSQL RPC `public.recommend_quests`.
- BQ5 validated end-to-end from the Kotlin app, including time filtering and immediate session-level “Not for me” exclusions.
- BQ8 recommendation-diversity experiment (Type 3). Backend migration 008 is
  applied in Supabase and adds the server-side `control`/`diverse` variant to
  `public.recommend_quests` (returns `variant`, `rank_position`, `category`).
  Flutter emits `variant`/`rank`/`batch_id` in `recommendation_shown` metadata.
  `BQ8_RECOMMENDATION_DIVERSITY_SQL` and the `bq8` pipeline job compute
  per-variant/week diversity metrics.
- Minimal Streamlit dashboard code for stored BQ outputs.
- BQ3 v2 for Kotlin: four-step onboarding drop-off and exactly linked first-quest
  acceptance, deduplicated by stable event IDs. Real Kotlin sources, Python batch
  execution, the stored result and the local Streamlit dashboard were verified
  with an explicitly labelled five-minute demonstration on 2026-10-29. This does
  not establish hosted dashboard deployment or a matured 24-hour result. See
  [BQ3_V2.md](BQ3_V2.md).
- BQ10 query and bq10 pipeline job: session-level location-independent usage with time-of-day and weather breakdowns.

## Implemented in code but not yet deployed end-to-end

- Python batch pipeline execution against the hosted Supabase database.
- Streamlit dashboard hosting.
- Refresh of `analytics.user_features` by the Python pipeline.
- Flutter BQ3 legacy events contain only two step completions. They cannot
  establish the full initial-setup funnel or first-recommendation acceptance and
  are excluded from the Kotlin v2 result. Flutter needs compatible versioned
  instrumentation before it can be included; historical rows are not changed.

- BQ7 query and `bq7` pipeline job: compares adoption and completion of group-labelled versus individual quests over the last 30 days, using `quests.is_group` and `user_quests`. The output explicitly distinguishes quest classification from verified group participation, which is not represented in the current schema.

## Planned / incomplete

- Scheduled deployment of the Python pipeline.
- Dedicated least-privilege ETL database role.
- Matured 24-hour BQ3 validation, beyond the verified five-minute demonstration.
- BQ4 query: instant-plan vs standard start-path comparison. Defines a
  `start_path`/`seconds_to_start`/`interactions_to_start` metadata contract
  (see EVENT_SCHEMA.md). No client emits it yet, so the query has only been
  checked against synthetic data; needs Kotlin/Flutter to emit these fields
  on `recommendation_accepted`/`quest_started`, then a pipeline run to
  confirm output in `analytics.bq_results`.
- Live BQ10 batch execution against hosted Supabase; the query and pipeline job are implemented and covered by CI tests, but the live run still needs to be demonstrated with real `location_independent_mode_selected` / `location_based_mode_selected` events.
- Weather external-service integration.
- Firebase Cloud Messaging.
- Google Maps Platform.
- Store-and-forward local analytics queue in Kotlin/Flutter.
- Realtime social/group-quest features.

## Architecture note

BQ5 currently lives in PostgreSQL as a shared RPC rather than an Edge Function. This is intentional for Sprint 2: both Kotlin and Flutter can call the same authenticated function through Supabase/PostgREST, so the ranking logic is not duplicated in the mobile clients. Moving it to an Edge Function later is optional and should only be done if context orchestration or external-service logic justifies the extra layer.

The architecture diagrams must distinguish implemented-and-validated, implemented-but-not-deployed, and planned components.
