# Analytics Pipeline

```text
Mobile action
   ↓
Kotlin / Flutter analytics adapter
   ↓
Supabase analytics_events
   ↓
BQ-specific SQL / RPC / Edge Function
   ↓
result
   ↓
app or Sprint 2 evidence
```

## Design goals

1. One event schema shared by Kotlin and Flutter.
2. One shared database.
3. Business Question logic lives outside platform-specific UI code.
4. Recommendation/BQ5 logic should be shared so Kotlin and Flutter do not implement different scoring rules.
5. Every BQ must be testable with reproducible data.
