# Analytics implementation status

## Implemented now

- Shared Supabase PostgreSQL database.
- Mobile event ingestion table: `public.analytics_events`.
- Analytics output schema: `analytics`.
- `analytics.user_features`.
- `analytics.bq_results`.
- Python/SQLAlchemy engine skeleton.
- BQ9 query: category completion rate for accepted quests in the last 30 days.
- BQ6 base query: abandonment reason segmented by duration and cost.
- User feature refresh based on completed quest history.
- Minimal Streamlit dashboard for stored BQ outputs.

## Not yet validated / still planned

- Scheduled deployment of the Python pipeline.
- Dedicated least-privilege ETL database role.
- Distance segmentation for BQ6.
- BQ3 onboarding drop-off (requires onboarding events).
- BQ5 runtime recommendation Edge Function.
- BQ8 diversity experiment metrics.
- BQ10 weather/time-of-day analysis.
- OpenWeather/Open-Meteo integration.
- Firebase Cloud Messaging.
- Google Maps Platform.
- Store-and-forward local analytics queue in Kotlin/Flutter.
- Realtime social/group-quest features.

The architecture diagrams must distinguish these planned components from the parts
that are already implemented and tested.
