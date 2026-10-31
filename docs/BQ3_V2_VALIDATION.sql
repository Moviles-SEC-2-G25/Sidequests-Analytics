-- Read-only. Run on the same Supabase project as the Android application.
-- 1. Received versioned events. A recently offline event may arrive later with
--    its original occurred_at; the event_id remains stable across retries.
select user_id, session_id as onboarding_id, event_type,
       metadata->>'step_name' as step_name,
       metadata->>'event_sequence' as event_sequence,
       quest_id, metadata->>'exposure_id' as exposure_id,
       metadata->>'attempt_id' as attempt_id, occurred_at
from public.analytics_events
where metadata->>'bq_key' = 'BQ3' and metadata->>'schema_version' = '2'
order by user_id, session_id, (metadata->>'event_sequence')::int, id;

-- 2. Lost network acknowledgements may produce duplicate deliveries.
--    BQ3 v2 deduplicates them; do not sum raw event row counts as users.
select user_id, metadata->>'event_id' as event_id, count(*) as deliveries
from public.analytics_events
where metadata->>'bq_key' = 'BQ3' and metadata->>'schema_version' = '2'
group by user_id, metadata->>'event_id'
having count(*) > 1;

-- 3. Every first acceptance should have its exact exposure, and an owned attempt.
select a.id, a.user_id, a.quest_id,
       exists (
         select 1 from public.analytics_events s
         where s.event_type = 'onboarding_first_recommendation_shown'
           and s.user_id = a.user_id and s.session_id = a.session_id
           and s.quest_id = a.quest_id
           and s.metadata->>'exposure_id' = a.metadata->>'exposure_id'
       ) as linked_first_exposure,
       exists (
         select 1 from public.user_quests uq
         where uq.id::text = a.metadata->>'attempt_id'
           and uq.user_id = a.user_id and uq.quest_id = a.quest_id
       ) as linked_owned_attempt
from public.analytics_events a
where a.event_type = 'onboarding_first_recommendation_accepted'
  and a.metadata->>'bq_key' = 'BQ3' and a.metadata->>'schema_version' = '2';

-- 4. Latest computed BQ3. Verify schema_version=2 and the intended horizon.
select id, computed_at, payload
from analytics.bq_results
where bq_key = 'BQ3'
order by computed_at desc, id desc
limit 1;

-- 5. A queue retry reuses storage_path. A real retake intentionally uses a new path.
select p.attempt_id, p.step_order, p.storage_path, count(*) as records,
       exists (select 1 from storage.objects s
               where s.bucket_id = 'quest-proofs' and s.name = p.storage_path) as object_exists
from public.quest_photo_proofs p
group by p.attempt_id, p.step_order, p.storage_path
order by p.attempt_id, p.step_order;
