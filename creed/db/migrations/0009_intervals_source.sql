-- A second place training data can come from: intervals.icu, for watches other than Garmin (COROS, Polar, Suunto,
-- Wahoo and more). Its rows sit beside Garmin's in the same tables with source = 'intervals', so every metric and
-- screen works unchanged. A deployment syncs one source at a time (CREED_DATA_SOURCE), and if both ever hold a day,
-- the views below prefer Garmin's own reading.

alter table daily_metric drop constraint daily_metric_source_check;
alter table daily_metric add constraint daily_metric_source_check
  check (source in ('api', 'export', 'manual', 'intervals'));

alter table sleep_night drop constraint sleep_night_source_check;
alter table sleep_night add constraint sleep_night_source_check
  check (source in ('api', 'export', 'manual', 'intervals'));

alter table activity drop constraint activity_source_check;
alter table activity add constraint activity_source_check
  check (source in ('api', 'export', 'manual', 'intervals'));

alter table raw_record drop constraint raw_record_source_check;
alter table raw_record add constraint raw_record_source_check
  check (source in ('api', 'export', 'manual', 'intervals'));

-- Manual beats Garmin's API, which beats intervals.icu, which beats the export.
create or replace view daily_metric_best with (security_invoker = true) as
select distinct on (calendar_date, metric) *
from daily_metric
order by calendar_date, metric,
         case source when 'manual' then 0 when 'api' then 1 when 'intervals' then 2 else 3 end;

create or replace view sleep_night_best with (security_invoker = true) as
select distinct on (calendar_date) *
from sleep_night
order by calendar_date,
         case source when 'manual' then 0 when 'api' then 1 when 'intervals' then 2 else 3 end;
