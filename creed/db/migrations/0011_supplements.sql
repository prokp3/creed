-- Supplements you take (omega-3, vitamin D…), daily, on certain days or a few times a week, and, for each day,
-- whether you took them. Logged by day, not by time. Same rules as the rest of the food logger (0005_food.sql): every key starts with user_id, ids come
-- from the phone, the newest change wins, a deletion beats any edit, and creed_member can see only the person's
-- own rows.

create table supplement (
  user_id    uuid not null references app_user (id) on delete cascade,
  id         uuid not null,
  name       text not null check (length(name) between 1 and 40),
  -- As you'd say it: "1 capsule", "2000 IU", "5 g". Free text, since nothing is worked out from it.
  dose       text check (length(dose) <= 40),
  -- How often: {"kind": "daily"}, {"kind": "days", "days": [0, 2, 4]} (0 is Monday), or
  -- {"kind": "weekly", "times": 2} (twice a week, any days). Checked in creed/db/food.py.
  schedule   jsonb not null default '{"kind": "daily"}'::jsonb check (jsonb_typeof(schedule) = 'object'),
  sort_order integer not null default 0,
  changed_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  primary key (user_id, id)
);

-- One row per supplement per day once you've ticked it. Unticking keeps the row with taken false, so a late tick
-- from another device can't win over a newer untick.
create table supplement_taken (
  user_id       uuid not null,
  supplement_id uuid not null,
  local_date    date not null,
  taken         boolean not null,
  changed_at    timestamptz not null,
  updated_at    timestamptz not null default now(),
  primary key (user_id, supplement_id, local_date),
  foreign key (user_id, supplement_id) references supplement (user_id, id) on delete cascade
);
create index supplement_taken_day on supplement_taken (user_id, local_date) where taken;

do $$
declare
  t text;
  r record;
begin
  foreach t in array array['supplement', 'supplement_taken'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('grant select, insert, update, delete on %I to creed_member', t);
    execute format('create policy own_rows on %I for all to creed_member '
                   'using (user_id = nullif(current_setting(''creed.user_id'', true), '''')::uuid) '
                   'with check (user_id = nullif(current_setting(''creed.user_id'', true), '''')::uuid)', t);
    for r in select rolname from pg_roles where rolname in ('anon', 'authenticated') loop
      execute format('revoke all on %I from %I', t, r.rolname);
    end loop;
  end loop;
end
$$;
