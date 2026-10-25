-- SKELETON: where the student is now (asked before the pathway) and an optional minor.
-- Additive and safe to re-run. Run once in the Supabase SQL editor (or `psql -f`).
-- Until it's applied, the API still saves profiles, just without these two fields.

alter table profiles add column if not exists stage text
  check (stage in ('high_school', 'community_college', 'transferred', 'returning'));
alter table profiles add column if not exists minor text;

-- Already on from schema.sql; repeated so this file stands on its own.
alter table profiles enable row level security;
