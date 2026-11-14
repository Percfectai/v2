-- Eternal Rivals storage for Percfectai v2.
-- Run in the Supabase SQL editor for project fyxofxprzffcdgbkdyax only.
-- Do not run this on PerfectNDA (czeovrjzlsfdcdvlbwoq).
--
-- The Flask server writes these tables with SUPABASE_SERVICE_ROLE_KEY.
-- That role bypasses RLS. anon and authenticated have no policies and no grants,
-- so the Data API cannot read them. rivals_journals is never selected by an
-- agent code path. rivals_turn_log rejects UPDATE and DELETE.

create table if not exists rivals_personas (
  id            uuid primary key default gen_random_uuid(),
  world_id      text not null check (char_length(world_id) between 1 and 64),
  user_id       text not null check (char_length(user_id) between 1 and 200),
  character_id  text not null check (character_id ~ '^[A-Za-z0-9_-]{1,64}$'),
  fields        jsonb not null default '{}'::jsonb,
  system_prompt text not null default '',
  updated_at    timestamptz not null default now(),
  unique (world_id, user_id, character_id)
);

create table if not exists rivals_memory (
  id            uuid primary key default gen_random_uuid(),
  world_id      text not null check (char_length(world_id) between 1 and 64),
  user_id       text not null check (char_length(user_id) between 1 and 200),
  character_id  text not null check (character_id ~ '^[A-Za-z0-9_-]{1,64}$'),
  body          jsonb not null default '{}'::jsonb,
  updated_at    timestamptz not null default now(),
  unique (world_id, user_id, character_id)
);

create table if not exists rivals_growth (
  id            uuid primary key default gen_random_uuid(),
  world_id      text not null check (char_length(world_id) between 1 and 64),
  user_id       text not null check (char_length(user_id) between 1 and 200),
  character_id  text not null check (character_id ~ '^[A-Za-z0-9_-]{1,64}$'),
  body          jsonb not null default '{}'::jsonb,
  updated_at    timestamptz not null default now(),
  unique (world_id, user_id, character_id)
);

create table if not exists rivals_journals (
  id            uuid primary key default gen_random_uuid(),
  world_id      text not null check (char_length(world_id) between 1 and 64),
  user_id       text not null check (char_length(user_id) between 1 and 200),
  character_id  text not null check (character_id ~ '^[A-Za-z0-9_-]{1,64}$'),
  journal_date  date not null,
  body          text not null default '',
  created_at    timestamptz not null default now(),
  unique (world_id, user_id, character_id, journal_date)
);

create table if not exists rivals_phone_messages (
  id            uuid primary key default gen_random_uuid(),
  world_id      text not null check (char_length(world_id) between 1 and 64),
  user_id       text not null check (char_length(user_id) between 1 and 200),
  character_id  text not null check (character_id ~ '^[A-Za-z0-9_-]{1,64}$'),
  sender        text not null default '',
  body          text not null default '',
  created_at    timestamptz not null default now()
);

create index if not exists rivals_phone_messages_owner_idx
  on rivals_phone_messages (world_id, user_id, character_id, created_at desc);

create table if not exists rivals_turn_log (
  id            uuid primary key default gen_random_uuid(),
  world_id      text not null check (char_length(world_id) between 1 and 64),
  user_id       text not null check (char_length(user_id) between 1 and 200),
  character_id  text not null check (character_id ~ '^[A-Za-z0-9_-]{1,64}$'),
  payload       jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);

create index if not exists rivals_turn_log_owner_idx
  on rivals_turn_log (world_id, user_id, character_id, created_at desc);

create or replace function rivals_reject_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'rivals_turn_log is append-only';
end;
$$;

drop trigger if exists rivals_turn_log_no_update on rivals_turn_log;
create trigger rivals_turn_log_no_update
  before update or delete on rivals_turn_log
  for each row execute function rivals_reject_mutation();

alter table rivals_personas enable row level security;
alter table rivals_memory enable row level security;
alter table rivals_growth enable row level security;
alter table rivals_journals enable row level security;
alter table rivals_phone_messages enable row level security;
alter table rivals_turn_log enable row level security;

alter table rivals_personas force row level security;
alter table rivals_memory force row level security;
alter table rivals_growth force row level security;
alter table rivals_journals force row level security;
alter table rivals_phone_messages force row level security;
alter table rivals_turn_log force row level security;

revoke all on table rivals_personas from public, anon, authenticated;
revoke all on table rivals_memory from public, anon, authenticated;
revoke all on table rivals_growth from public, anon, authenticated;
revoke all on table rivals_journals from public, anon, authenticated;
revoke all on table rivals_phone_messages from public, anon, authenticated;
revoke all on table rivals_turn_log from public, anon, authenticated;
