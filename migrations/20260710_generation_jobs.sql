-- Distributed studio generation queue (100+ concurrent workers).
-- Run in Supabase SQL editor before enabling STUDIO_QUEUE_BACKEND=postgres.

create table if not exists generation_jobs (
  id           uuid primary key default gen_random_uuid(),
  user_id      bigint not null references users(id) on delete cascade,
  kind         text not null check (kind in (
    'image','batch','video','extend','arena','spin','fight',
    'api_video','api_image','character_one','character_finalize',
    'character_refine','character_restyle','character_adjust',
    'princess_image','picture_logo'
  )),
  payload      jsonb not null default '{}',
  status       text not null default 'pending'
               check (status in ('pending','processing','done','failed')),
  result       jsonb,
  error        text,
  worker_id    text,
  key_slot     int,
  created_at   timestamptz not null default now(),
  started_at   timestamptz,
  finished_at  timestamptz
);

create index if not exists idx_generation_jobs_pending
  on generation_jobs (created_at)
  where status = 'pending';

create index if not exists idx_generation_jobs_user
  on generation_jobs (user_id, created_at desc);

-- Atomically claim the oldest pending job (safe across many worker processes).
create or replace function claim_studio_job(p_worker_id text)
returns generation_jobs
language plpgsql
as $$
declare
  claimed generation_jobs;
begin
  update generation_jobs g
  set
    status = 'processing',
    worker_id = p_worker_id,
    started_at = now()
  from (
    select id
    from generation_jobs
    where status = 'pending'
    order by created_at
    for update skip locked
    limit 1
  ) c
  where g.id = c.id
  returning g.* into claimed;

  return claimed;
end;
$$;

-- Jobs ahead of this one still waiting (for queue UI).
create or replace function studio_queue_ahead(p_job_id uuid)
returns int
language sql
stable
as $$
  select count(*)::int
  from generation_jobs pending
  join generation_jobs mine on mine.id = p_job_id
  where pending.status = 'pending'
    and pending.created_at < mine.created_at;
$$;