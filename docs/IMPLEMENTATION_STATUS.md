# Analytics implementation status

## Implemented and validated

- Shared Supabase PostgreSQL database.
- Mobile event ingestion through `public.analytics_events`.
- Real Kotlin events validated in Supabase, including `recommendation_shown` and `recommendation_skipped`.
- Analytics output schema: `analytics`.
- `analytics.user_features`.
- `analytics.bq_results`.
- Python/SQLAlchemy analytics engine skeleton with automated CI tests.
- BQ9 query: category completion rate for accepted quests in the last 30 days.
- BQ6 base query: abandonment reason segmented by duration and cost.
- BQ5 shared runtime recommender implemented as the authenticated PostgreSQL RPC `public.recommend_quests`.
- BQ5 validated end-to-end from the Kotlin app, including time filtering and immediate session-level “Not for me” exclusions.
- Minimal Streamlit dashboard code for stored BQ outputs.

## Implemented in code but not yet deployed end-to-end

- Python batch pipeline execution against the hosted Supabase database.
- Streamlit dashboard hosting.
- Refresh of `analytics.user_features` by the Python pipeline.

## Planned / incomplete

- Scheduled deployment of the Python pipeline.
- Dedicated least-privilege ETL database role.
- Distance segmentation for BQ6.
- BQ3 onboarding drop-off (requires onboarding events).
- BQ8 diversity experiment metrics.
- BQ10 weather/time-of-day analysis.
- Weather external-service integration.
- Firebase Cloud Messaging.
- Google Maps Platform.
- Store-and-forward local analytics queue in Kotlin/Flutter.
- Realtime social/group-quest features.

## Architecture note

BQ5 currently lives in PostgreSQL as a shared RPC rather than an Edge Function. This is intentional for Sprint 2: both Kotlin and Flutter can call the same authenticated function through Supabase/PostgREST, so the ranking logic is not duplicated in the mobile clients. Moving it to an Edge Function later is optional and should only be done if context orchestration or external-service logic justifies the extra layer.

The architecture diagrams must distinguish implemented-and-validated, implemented-but-not-deployed, and planned components.
