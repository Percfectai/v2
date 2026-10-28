-- Run this in your Supabase SQL editor

create table if not exists users (
  id               bigserial primary key,
  username         text unique not null,
  password         text not null,
  email            text,
  birthday         text,
  is_adult         boolean default false,
  signup_ip        text,
  is_admin         boolean default false,
  api_key1         text unique,
  api_key2         text unique,
  images_today     int default 0,
  videos_today     int default 0,
  last_reset       timestamptz default now(),
  picture_credits  int default 0,
  video_credits    int default 0,
  tickets          int default 0,
  tickets_daily_at date,
  created_at       timestamptz default now()
);

-- Run these if upgrading an existing database:
alter table users add column if not exists email text;
alter table users add column if not exists display_name text;
alter table users add column if not exists is_adult boolean default false;
alter table users add column if not exists signup_ip text;
alter table users add column if not exists is_admin boolean default false;
alter table users add column if not exists stripe_customer_id text;
alter table users add column if not exists social_twitter text;
alter table users add column if not exists social_instagram text;
alter table users add column if not exists social_tiktok text;
alter table users add column if not exists social_youtube text;
alter table users add column if not exists social_website text;
alter table users add column if not exists tickets int default 0;
alter table users add column if not exists tickets_daily_at date;
-- V2 studio unlocks / billing (required by app.py studio pages + Stripe)
alter table users add column if not exists has_purchased boolean default false;
alter table users add column if not exists stripe_subscription_plan text;


-- Trading / Battle card progression (level 1–4 · unlock abilities)
alter table characters add column if not exists card_level int default 1;
alter table characters add column if not exists card_xp int default 0;
update users set is_adult = true where birthday is not null and birthday <> '' and birthday::date <= (current_date - interval '18 years');

-- Allow guest princess generations in history (optional)
alter table generations alter column user_id drop not null;

create table if not exists generations (
  id          bigserial primary key,
  user_id     bigint references users(id) on delete cascade,
  type        text check (type in ('image','video')),
  prompt      text,
  output_url  text,
  created_at  timestamptz default now()
);

-- Promo / offer codes (free credits or limited-use campaigns)
create table if not exists promo_codes (
  id                 bigserial primary key,
  code               text unique not null,
  description        text,
  image_credits      int default 0,
  video_credits      int default 0,
  max_uses           int,
  uses_count         int default 0,
  max_uses_per_user  int default 1,
  expires_at         timestamptz,
  active             boolean default true,
  created_at         timestamptz default now()
);

create table if not exists promo_redemptions (
  id            bigserial primary key,
  user_id       bigint references users(id) on delete cascade,
  promo_code_id bigint references promo_codes(id) on delete cascade,
  redeemed_at   timestamptz default now(),
  unique(user_id, promo_code_id)
);

-- Private promo ladder (never list codes on public UI).
-- image_credits = unified wallet credits (1 credit = 1 image · ~6 credits = 1s video).
-- Ladder: Launch 25 · Sultan 50 · DA VIP 75 (= Try pack) · Motion 60 (~10s video).
insert into promo_codes (code, description, image_credits, video_credits, max_uses, max_uses_per_user, active)
values
  ('LAUNCH', 'Launch welcome — 25 wallet credits', 25, 0, null, 1, true),
  ('SULTANSPECIAL', 'Sultan VIP — 50 wallet credits', 50, 0, null, 1, true),
  ('DEVIANTVIP', 'DeviantArt VIP — 75 wallet credits (full Try pack)', 75, 0, null, 1, true),
  ('MOTIONLAUNCH', 'Motion launch — 60 wallet credits (~10s video or 60 images)', 60, 0, null, 1, true)
on conflict (code) do update set
  description = excluded.description,
  image_credits = excluded.image_credits,
  video_credits = excluded.video_credits,
  max_uses_per_user = excluded.max_uses_per_user,
  active = excluded.active;

-- Distributed generation queue (see migrations/20260710_generation_jobs.sql)
-- create table generation_jobs (...); claim_studio_job(); studio_queue_ahead();

-- Storage bucket for user uploads (optional, since xAI returns URLs directly)
-- Create a public bucket named "generations" in Supabase Storage dashboard
-- if you want to mirror/cache generated files.

-- Percfect API v1 keys + jobs: see migrations/20261001_api_keys.sql
create table if not exists api_keys (
  id            uuid primary key default gen_random_uuid(),
  user_id       bigint not null references users(id) on delete cascade,
  name          text default 'default',
  key_prefix    text not null,              -- e.g. "pk_live_a1b2c3" (safe to show)
  key_hash      text not null unique,       -- sha256 of the full key
  created_at    timestamptz default now(),
  last_used_at  timestamptz,
  revoked_at    timestamptz
);

create index if not exists api_keys_user_idx on api_keys(user_id);

-- Jobs started through the API. One API job = the site's two existing jobs
-- (character_one front shot → character_pack 360 + angles), tracked by stage.
create table if not exists api_jobs (
  id              uuid primary key default gen_random_uuid(),
  user_id         bigint not null references users(id) on delete cascade,
  api_key_id      uuid references api_keys(id),
  status          text not null default 'queued',   -- queued | running | success | failed
  stage           text not null default 'front',    -- front | pack_starting | pack | angles | done
  include_360     boolean default false,
  internal_job_id text,                             -- generation_jobs id of the current stage
  front_url       text,
  outputs         jsonb,                            -- {"front","left","back","right","spin_360"} urls
  error           text,
  credits_charged int default 0,                    -- credits held at start; refunded in full on failure
  created_at      timestamptz default now(),
  updated_at      timestamptz default now()
);

create index if not exists api_jobs_user_idx on api_jobs(user_id);
