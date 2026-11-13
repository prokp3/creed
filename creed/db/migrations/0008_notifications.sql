-- Which training notifications have gone out (Recovery, workout recaps, load spike, weekly summary, Garmin key,
-- sync failed), so each one goes out once however often the schedule runs. Only the server reads this.
create table notification_sent (
  user_id    uuid not null references app_user (id) on delete cascade,
  -- recovery, workout, load_spike, weekly, key_expiring or sync_failed.
  kind       text not null check (kind in ('recovery', 'workout', 'load_spike', 'weekly', 'key_expiring', 'sync_failed')),
  -- What makes it one notification: a date, an activity id, a week, a key warning step or a run of failures.
  ref        text not null,
  -- sent, seen (already shown in the app, so not sent) or failed (no phone took it).
  outcome    text not null check (outcome in ('sent', 'seen', 'failed')),
  sent_at    timestamptz not null default now(),
  primary key (user_id, kind, ref)
);
create index notification_sent_recent on notification_sent (user_id, kind, sent_at desc);

do $$
declare
  r record;
begin
  alter table notification_sent enable row level security;
  alter table notification_sent force row level security;
  for r in select rolname from pg_roles where rolname in ('anon', 'authenticated') loop
    execute format('revoke all on notification_sent from %I', r.rolname);
  end loop;
end
$$;
