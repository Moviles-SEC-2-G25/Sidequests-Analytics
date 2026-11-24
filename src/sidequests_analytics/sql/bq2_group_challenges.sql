-- BQ2: observed membership and server-received create/join/progress requests.
-- Every request is idempotent; transport failures that never reach the RPC
-- are not observable. Counts of members include the creator.
with operation_names as (
    select unnest(array['create','join','progress']) as operation
), operations as (
    select operation, count(*)::integer as attempts,
           count(*) filter(where succeeded)::integer as successes,
           count(*) filter(where not succeeded)::integer as failures
    from sidequests_group_private.operations
    where occurred_at >= now() - interval '30 days'
    group by operation
), client_requests as (
    select distinct ae.user_id, ae.metadata->>'request_id' as request_id,
           ae.metadata->>'operation' as operation
    from public.analytics_events ae
    where ae.event_type='group_challenge_client_unconfirmed'
      and ae.occurred_at >= now()-interval '30 days'
      and ae.metadata->>'request_id' is not null
      and ae.metadata->>'operation' in ('create','join','progress')
), client_summary as (
    select cr.operation,count(*)::integer as client_unconfirmed,
           count(*) filter(where o.request_id is null)::integer as no_server_record
    from client_requests cr
    left join sidequests_group_private.operations o
      on o.user_id=cr.user_id and o.request_id::text=cr.request_id and o.operation=cr.operation
    group by cr.operation
), group_counts as (
    select c.id, q.title, c.expires_at > now() as active,
           count(m.user_id)::integer as participants,
           count(m.user_id) filter(where m.user_id<>c.owner_id)::integer as joined_non_creators,
           count(m.user_id) filter(where m.progress=c.total_steps)::integer as completed_participants
    from sidequests_group_private.challenges c
    join public.quests q on q.id=c.quest_id
    left join sidequests_group_private.members m on m.challenge_id=c.id
    where c.created_at >= now()-interval '30 days'
    group by c.id,q.title
)
select 'operation'::text as row_type, n.operation, null::text as challenge_id,
       null::text as quest_title, null::boolean as active,
       coalesce(o.attempts,0) as attempts, coalesce(o.successes,0) as successes,
       coalesce(o.failures,0) as failures,
       round(100.0*o.failures/nullif(o.attempts,0),2) as failure_rate_pct,
       coalesce(cs.client_unconfirmed,0) as client_unconfirmed,
       coalesce(cs.no_server_record,0) as no_server_record,
       null::integer as participants, null::integer as joined_non_creators, null::integer as completed_participants
from operation_names n left join operations o using(operation)
left join client_summary cs using(operation)
union all
select 'challenge',null,id::text,title,active,null,null,null,null,null,null,participants,joined_non_creators,completed_participants
from group_counts
order by row_type,operation,challenge_id;
