-- Per-person food settings, phones that can receive notifications, and which reminders have gone out.

-- One row per person, made the first time they change anything. No row means the defaults.
create table food_setting (
  user_id              uuid primary key references app_user (id) on delete cascade,
  -- A day with a synced workout at least this long is a training day.
  training_minutes     integer not null default 20 check (training_minutes between 1 and 600),
  reminders_on         boolean not null default false,
  -- Local clock times such as 13:30, in the time zone below.
  reminder_times       text[] not null default '{}',
  -- A reminder is skipped if anything was logged this recently.
  reminder_gap_minutes integer not null default 180 check (reminder_gap_minutes between 30 and 1440),
  timezone             text not null default 'Asia/Kolkata',
  changed_at           timestamptz not null,
  updated_at           timestamptz not null default now()
);

-- A phone or browser that has agreed to notifications, as the browser described it. Only the server reads these.
create table push_subscription (
  endpoint    text primary key,
  user_id     uuid not null references app_user (id) on delete cascade,
  p256dh      text not null,
  auth        text not null,
  created_at  timestamptz not null default now(),
  last_ok_at  timestamptz
);
create index push_subscription_user on push_subscription (user_id);

-- So a reminder goes out once per slot per day, however often the schedule runs.
create table food_reminder_sent (
  user_id    uuid not null references app_user (id) on delete cascade,
  local_date date not null,
  slot       text not null,
  -- sent, skipped (something was logged recently) or failed.
  outcome    text not null check (outcome in ('sent', 'skipped', 'failed')),
  sent_at    timestamptz not null default now(),
  primary key (user_id, local_date, slot)
);

do $$
declare
  t text;
  r record;
begin
  foreach t in array array['food_setting', 'push_subscription', 'food_reminder_sent'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    for r in select rolname from pg_roles where rolname in ('anon', 'authenticated') loop
      execute format('revoke all on %I from %I', t, r.rolname);
    end loop;
  end loop;
end
$$;

-- Food settings are read and changed while acting for the person, like the rest of their food.
grant select, insert, update, delete on food_setting to creed_member;
create policy own_rows on food_setting for all to creed_member
  using (user_id = nullif(current_setting('creed.user_id', true), '')::uuid)
  with check (user_id = nullif(current_setting('creed.user_id', true), '')::uuid);
