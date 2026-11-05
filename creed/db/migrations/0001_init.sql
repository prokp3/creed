-- Creed's first schema. One deployment serves one person, so there is no user table.
--
-- Dates and times:
--   * calendar_date is Garmin's own day, kept as given.
--   * Sleep and HRV belong to the date you woke up. On real data calendarDate matched
--     the wake date on every one of 203 nights.
--   * Timestamps are stored in UTC. utc_offset_minutes records the wearer's local offset
--     at the time, so a past day still displays correctly after travel.
--
-- Sources:
--   * source says where a row came from: api, export or manual. Rows from different
--     sources sit side by side, so the importer and manual entries (hydration, weight)
--     need no schema change. The *_best views pick one row per day.
--
-- Quality:
--   * Nothing is ever imputed. A missing day has no row. A value that fails validation
--     is stored with quality = 'flagged' and explained in quality_flag, so metrics can
--     leave it out and the Data Quality page can show why.

create table app_setting (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);

create table app_secret (
  name       text primary key,
  value      text not null,
  expires_at timestamptz,
  updated_at timestamptz not null default now()
);

-- One value per day per metric. A new metric or manual entry is a new row, not a new column.
create table daily_metric (
  calendar_date date not null,
  metric        text not null,
  source        text not null check (source in ('api', 'export', 'manual')),
  value_num     double precision,
  value_text    text,
  quality       text not null default 'ok' check (quality in ('ok', 'flagged')),
  updated_at    timestamptz not null default now(),
  primary key (calendar_date, metric, source),
  check (value_num is not null or value_text is not null)
);
create index daily_metric_metric_date on daily_metric (metric, calendar_date);

create table sleep_night (
  calendar_date        date not null,
  source               text not null check (source in ('api', 'export', 'manual')),
  sleep_start          timestamptz,
  sleep_end            timestamptz,
  utc_offset_minutes   integer,
  sleep_seconds        integer,
  deep_seconds         integer,
  light_seconds        integer,
  rem_seconds          integer,
  awake_seconds        integer,
  unmeasurable_seconds integer,
  nap_seconds          integer,
  score_overall        integer,
  score_qualifier      text,
  respiration_avg      double precision,
  respiration_low      double precision,
  respiration_high     double precision,
  avg_sleep_stress     double precision,
  awake_count          integer,
  confirmation         text,
  from_device          boolean,
  rem_capable          boolean,
  quality              text not null default 'ok' check (quality in ('ok', 'flagged')),
  updated_at           timestamptz not null default now(),
  primary key (calendar_date, source)
);

-- Garmin's activity ID is the natural key, and the export carries it too.
create table activity (
  activity_id        bigint primary key,
  source             text not null check (source in ('api', 'export', 'manual')),
  parent_id          bigint,
  is_parent          boolean not null default false,
  type_key           text,
  discipline         text not null check (discipline in ('swim', 'bike', 'run', 'multisport', 'other')),
  start_time         timestamptz,
  local_date         date,
  utc_offset_minutes integer,
  duration_seconds   double precision,
  moving_seconds     double precision,
  elapsed_seconds    double precision,
  distance_m         double precision,
  avg_speed_mps      double precision,
  avg_hr             double precision,
  max_hr             double precision,
  garmin_load        double precision,
  aerobic_effect     double precision,
  anaerobic_effect   double precision,
  moderate_minutes   integer,
  vigorous_minutes   integer,
  -- Power stays nullable: runs report it today, and rides will once a bike computer arrives.
  avg_power          double precision,
  max_power          double precision,
  norm_power         double precision,
  pool_length_m      double precision,
  active_lengths     integer,
  strokes            double precision,
  avg_swolf          double precision,
  is_manual          boolean not null default false,
  quality            text not null default 'ok' check (quality in ('ok', 'flagged')),
  fit_status         text not null default 'pending' check (fit_status in ('pending', 'ok', 'failed', 'none')),
  fit_attempts       integer not null default 0,
  updated_at         timestamptz not null default now()
);
create index activity_local_date on activity (local_date);
-- For matching export rows that lack an ID.
create index activity_start_type on activity (start_time, type_key);

-- The original file as Garmin sent it. Real ones are 9-65 KB, so this fits the free tier for years.
create table activity_file (
  activity_id bigint primary key references activity (activity_id) on delete cascade,
  content     bytea not null,
  sha256      text not null,
  fetched_at  timestamptz not null default now()
);

-- Responses as received, so a Garmin schema change can be re-read without fetching again.
create table raw_record (
  dataset    text not null,
  record_key text not null,
  source     text not null check (source in ('api', 'export', 'manual')),
  body       jsonb not null,
  fetched_at timestamptz not null default now(),
  primary key (dataset, record_key, source)
);

create table quality_flag (
  scope       text not null,
  ref_key     text not null,
  code        text not null,
  severity    text not null check (severity in ('info', 'warning', 'problem')),
  detail      text not null,
  first_seen  timestamptz not null default now(),
  last_seen   timestamptz not null default now(),
  resolved_at timestamptz,
  primary key (scope, ref_key, code)
);
create index quality_flag_open on quality_flag (severity, last_seen) where resolved_at is null;

create table sync_cursor (
  dataset         text primary key,
  newest_date     date,
  oldest_date     date,
  first_data_date date,
  backfill_done   boolean not null default false,
  empty_days      integer not null default 0,
  window_days     integer,
  page_offset     integer not null default 0,
  updated_at      timestamptz not null default now()
);

create table sync_run (
  id          bigint generated always as identity primary key,
  trigger     text not null,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  status      text not null default 'running'
              check (status in ('running', 'ok', 'partial', 'auth_failed', 'failed')),
  requests    integer not null default 0,
  records     integer not null default 0,
  backfill_pending boolean not null default true,
  message     text,
  details     jsonb not null default '{}'::jsonb
);
create index sync_run_started on sync_run (started_at desc);

-- Manual beats the API, and the API beats the export.
create view daily_metric_best with (security_invoker = true) as
select distinct on (calendar_date, metric) *
from daily_metric
order by calendar_date, metric,
         case source when 'manual' then 0 when 'api' then 1 else 2 end;

create view sleep_night_best with (security_invoker = true) as
select distinct on (calendar_date) *
from sleep_night
order by calendar_date,
         case source when 'manual' then 0 when 'api' then 1 else 2 end;

-- All database access is server side. Row-level security with no policies, plus revoked
-- grants, means Supabase's public API roles can read nothing even if a key leaks.
do $$
declare
  t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;

  -- Supabase grants these roles access to every new table by default, so close that too.
  for t in select rolname from pg_roles where rolname in ('anon', 'authenticated') loop
    execute format('revoke all on all tables in schema public from %I', t.rolname);
    execute format('revoke all on all sequences in schema public from %I', t.rolname);
    execute format('alter default privileges in schema public revoke all on tables from %I', t.rolname);
    execute format('alter default privileges in schema public revoke all on sequences from %I', t.rolname);
  end loop;
end
$$;
