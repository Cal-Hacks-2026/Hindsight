-- Opportunities: ten categories, programs, fits your week.
-- Run once in the Supabase SQL editor after schema.sql. Safe to run again.

-- When and where a listing happens, as the source states it (null when it doesn't).
alter table opportunities add column if not exists ends_at timestamptz;
alter table opportunities add column if not exists location text;
alter table opportunities add column if not exists modality text;
do $$ begin
  alter table opportunities add constraint opportunities_modality_check
    check (modality in ('in_person', 'online', 'hybrid'));
exception when duplicate_object then null;
end $$;

-- Category labels Claude wrote for listings the keyword rules couldn't place
-- (apps/api/app/services/radar/classify.py). Rule labels are computed on read and not stored.
-- title_hash ties a label to the title it was written for; a retitled listing is labeled again.
create table if not exists opportunity_labels (
  opportunity_id uuid primary key references opportunities(id) on delete cascade,
  category text not null,
  subcategory text not null,
  title_hash text not null,
  labeled_at timestamptz not null default now()
);

-- The API uses the service-role key (bypasses RLS); RLS keeps the browser's anon key out.
alter table opportunity_labels enable row level security;
