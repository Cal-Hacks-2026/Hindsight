-- Class schedule (SCHEDULE): a student's confirmed class meetings, one row per meeting
-- pattern (a lecture and its lab are two rows with the same CRN).
-- Run once in the Supabase SQL editor (or `psql -f`) after schema.sql.

create table if not exists class_schedule (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references profiles(id) on delete cascade,
  position int not null default 0,  -- order on the confirmed list
  term text not null,
  course text not null,
  title text,
  crn text,
  section text,
  professor text,
  units numeric,
  location text,
  mode text not null check (mode in ('in_person', 'online', 'hybrid', 'asynchronous')),
  days text[] not null default '{}'
    check (days <@ array['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']),
  start_time time,
  end_time time,
  start_date date,
  end_date date,
  created_at timestamptz not null default now(),
  check ((start_time is null) = (end_time is null)),
  check (end_time > start_time),
  check (end_date >= start_date)
);
create index if not exists class_schedule_profile_idx on class_schedule(profile_id, position);

-- The API uses the service-role key, which bypasses RLS; RLS on keeps the browser's anon key out.
alter table class_schedule enable row level security;
