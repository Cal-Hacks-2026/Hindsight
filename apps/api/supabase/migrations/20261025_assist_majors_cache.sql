-- MAJORS-FALLBACK: every live ASSIST majors list, one row per college → university pair and year,
-- so a pair that has loaded once still works when ASSIST is down. Replaced on each live load.
-- Written and read only by the API with the service-role key; RLS on with no policies keeps
-- the anon key out, as for articulation_cache.

create table if not exists assist_majors_cache (
  sending_id int not null,
  receiving_id int not null,
  year_id int not null,
  payload jsonb not null,          -- ASSIST's majors reports for the pair, as returned
  fetched_at timestamptz not null default now(),
  primary key (sending_id, receiving_id, year_id)
);

alter table assist_majors_cache enable row level security;
