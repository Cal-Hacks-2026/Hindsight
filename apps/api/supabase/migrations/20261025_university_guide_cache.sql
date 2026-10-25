-- Your University guide cache (apps/api/app/services/university/store.py).
-- Run once in the Supabase SQL editor (or `psql -f`), after schema.sql.
--   key 'guide:<university id>'               payload: the built guide, with quotes and input hashes
--   key 'page:<university id>:<source id>'    payload: one source page's text as read on fetched_at

create table if not exists university_guide_cache (
  key text primary key,
  university_id int not null,
  kind text not null check (kind in ('guide', 'page')),
  payload jsonb not null,
  fetched_at timestamptz not null default now()
);
create index if not exists university_guide_cache_university_idx on university_guide_cache(university_id, kind);

-- The API uses the service-role key, which bypasses RLS; RLS keeps the browser's anon key out.
alter table university_guide_cache enable row level security;
