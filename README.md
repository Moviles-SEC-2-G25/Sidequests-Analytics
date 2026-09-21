# Sidequests Analytics

Shared analytics engine for the Sidequests Kotlin and Flutter applications.

Both mobile clients write the same event contract into the shared Supabase backend.
This repository owns the Business Question logic, recommendation analytics and pipeline documentation.

## Initial Sprint 2 scope

Implemented/selected Business Questions:
- BQ3 — Onboarding Drop-off (Type 2)
- BQ5 — Personalized Quest Recommendation (Type 2)
- BQ6 — Quest Abandonment Reasons (Type 2)
- BQ8 — Recommendation Diversity (Type 3)
- BQ9 — Quest Category Performance (Type 3)
- BQ10 — Location-Independent Mode Usage (Type 3)

## Shared pipeline

```text
Kotlin / Flutter
      ↓
analytics_events
      ↓
BQ queries / functions
      ↓
BQ results / recommendation response
      ↓
Kotlin / Flutter / Sprint 2 evidence
```

The analytics engine uses the same Supabase project and database as the backend. It does not maintain a second database.
