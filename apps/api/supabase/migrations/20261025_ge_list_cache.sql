-- GE progress: cached ASSIST Cal-GETC / IGETC course lists, one row per college, list and year.
-- Written and read only by the API with the service-role key; RLS on with no policies keeps
-- the anon key out, as for articulation_cache.

create table if not exists ge_list_cache (
  key text primary key,            -- "CALGETC/113/77"
  list_type text not null,         -- ASSIST listType: CALGETC or IGETC
  institution_id int not null,
  year_id int not null,
  payload jsonb not null,          -- the list, trimmed to the fields the API reads
  fetched_at timestamptz not null default now()
);

alter table ge_list_cache enable row level security;
