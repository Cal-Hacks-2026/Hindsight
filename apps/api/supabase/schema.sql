-- Hindsight schema v1 — PROJECT.md §9.
-- Run once in the Supabase SQL editor (or `psql -f`). Not yet applied anywhere.

create extension if not exists pgcrypto;

create table if not exists profiles (
  id uuid primary key default gen_random_uuid(),
  name text,
  sending_institution_id int,
  receiving_institution_id int,
  campus text,
  majors text[] not null default '{}',
  goals text,
  interests text[] not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists transcript_courses (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references profiles(id) on delete cascade,
  prefix text,
  number text,
  title text,
  units numeric,
  grade text,
  term text,
  academic_year_id int,
  confirmed bool not null default false
);
create index if not exists transcript_courses_profile_idx on transcript_courses(profile_id);

create table if not exists articulation_cache (
  key text primary key,
  sending_id int,
  receiving_id int,
  year_id int,
  major_label text,
  payload jsonb,
  fetched_at timestamptz not null default now()
);

create table if not exists match_results (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references profiles(id) on delete cascade,
  major_label text,
  result jsonb,
  created_at timestamptz not null default now()
);
create index if not exists match_results_profile_idx on match_results(profile_id);

create table if not exists plans (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references profiles(id) on delete cascade,
  semesters jsonb,
  created_at timestamptz not null default now()
);
create index if not exists plans_profile_idx on plans(profile_id);

create table if not exists opportunities (
  id uuid primary key default gen_random_uuid(),
  campus text,
  type text,
  title text,
  org text,
  starts_at timestamptz,
  deadline timestamptz,
  url text unique,
  description text,
  tags text[] not null default '{}',
  scraped_at timestamptz not null default now()
);

create table if not exists profile_opportunities (
  profile_id uuid not null references profiles(id) on delete cascade,
  opportunity_id uuid not null references opportunities(id) on delete cascade,
  score numeric,
  reason text,
  notified bool not null default false,
  primary key (profile_id, opportunity_id)
);

create table if not exists agent_events (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null,
  kind text not null check (kind in ('plan', 'step', 'diff', 'result', 'error')),
  message text,
  payload jsonb,
  created_at timestamptz not null default now()
);
create index if not exists agent_events_run_idx on agent_events(run_id, created_at);

-- The API talks to Postgres with the service-role key, which bypasses RLS.
-- RLS stays on so the anon key exposed to the browser can't read tables directly.
alter table profiles enable row level security;
alter table transcript_courses enable row level security;
alter table articulation_cache enable row level security;
alter table match_results enable row level security;
alter table plans enable row level security;
alter table opportunities enable row level security;
alter table profile_opportunities enable row level security;
alter table agent_events enable row level security;

-- Private Storage bucket for transcripts (PROJECT.md §6: stored under the user's profile only).
insert into storage.buckets (id, name, public)
values ('transcripts', 'transcripts', false)
on conflict (id) do nothing;
