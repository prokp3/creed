-- Numbers worked out once from each FIT file, so metrics never re-read the files.
-- hr_seconds lets load be recalculated when max or resting HR changes.
create table activity_derived (
  activity_id      bigint primary key references activity (activity_id) on delete cascade,
  derive_version   integer not null,
  samples          integer not null,
  hr_coverage      double precision,
  hr_seconds       jsonb not null default '{}'::jsonb,
  steady           boolean not null default false,
  efficiency       double precision,
  decoupling_pct   double precision,
  steady_speed_mps double precision,
  steady_hr        double precision,
  updated_at       timestamptz not null default now()
);
alter table activity_derived enable row level security;
