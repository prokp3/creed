-- The food logger. Every row belongs to one user (see 0004_users.sql), and every key starts with user_id, so
-- one person's ids can never point at another person's foods, presets or entries.
--
-- Nutrition:
--   * A food's values are stored per 100 g, or per 100 ml for a liquid (its base). Values entered per
--     piece or per serving are converted before saving.
--   * Nutrient values are a JSON object keyed by food_nutrient.id, so a custom nutrient (caffeine,
--     creatine) needs no new column. A missing key means unknown, never zero.
--   * A log entry keeps its own copy of the food's name, values and units, so editing or deleting a
--     food never changes a past day.
--
-- Sync (the phone logs offline and sends its changes later):
--   * Every id is a UUID made on the phone, so sending the same change twice can't make a second row.
--   * changed_at is when the change was made on the phone. The newest change to a record wins.
--   * deleted_at marks a deletion. It's kept rather than removing the row, so a late edit from another
--     device can't bring the record back: a deletion beats any edit.
--
-- Privacy: the server's own database role skips row-level security, so food queries switch to creed_member,
-- a role that can't, with the user's id set for the transaction. The policies below then let a query see and
-- write only that user's rows, even if the query itself forgot to say whose rows it wanted.

create table food_nutrient (
  user_id    uuid not null references app_user (id) on delete cascade,
  id         text not null,
  name       text not null check (length(name) between 1 and 40),
  unit       text not null check (length(unit) between 1 and 12),
  built_in   boolean not null default false,
  sort_order integer not null default 0,
  changed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  primary key (user_id, id),
  -- The seven everyone has can be renamed but not deleted.
  check (not built_in or deleted_at is null)
);

create table food (
  user_id      uuid not null references app_user (id) on delete cascade,
  id           uuid not null,
  name         text not null check (length(name) between 1 and 80),
  brand        text check (length(brand) <= 80),
  barcode      text check (barcode ~ '^[0-9]{6,14}$'),
  base         text not null check (base in ('g', 'ml')),
  nutrients    jsonb not null default '{}'::jsonb check (jsonb_typeof(nutrients) = 'object'),
  -- 'g' or 'ml' (its base), or the name of one of its food_unit rows.
  default_unit text not null,
  favourite    boolean not null default false,
  source       text not null check (source in ('seed', 'manual', 'barcode', 'import')),
  notes        text check (length(notes) <= 500),
  changed_at   timestamptz not null default now(),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz,
  primary key (user_id, id)
);
create index food_live_name on food (user_id, lower(name)) where deleted_at is null;
-- One live food per barcode for each person, so a scan finds the food you already saved.
create unique index food_live_barcode on food (user_id, barcode) where barcode is not null and deleted_at is null;

-- How much of the base one unit is: a piece of egg is 50 g, a cup of milk is 240 ml.
create table food_unit (
  user_id uuid not null,
  food_id uuid not null,
  name    text not null check (length(name) between 1 and 20 and name not in ('g', 'ml')),
  amount  double precision not null check (amount > 0 and amount <= 100000),
  primary key (user_id, food_id, name),
  foreign key (user_id, food_id) references food (user_id, id) on delete cascade
);

create table food_preset (
  user_id    uuid not null references app_user (id) on delete cascade,
  id         uuid not null,
  name       text not null check (length(name) between 1 and 40),
  sort_order integer not null default 0,
  changed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  primary key (user_id, id)
);

-- A preset's items are always written together with the preset, so they need no sync fields of their own.
create table food_preset_item (
  user_id   uuid not null,
  preset_id uuid not null,
  position  integer not null check (position >= 0),
  food_id   uuid not null,
  quantity  double precision not null check (quantity > 0 and quantity <= 100000),
  unit      text not null,
  primary key (user_id, preset_id, position),
  foreign key (user_id, preset_id) references food_preset (user_id, id) on delete cascade,
  foreign key (user_id, food_id) references food (user_id, id) on delete cascade
);

create table food_log_entry (
  user_id            uuid not null references app_user (id) on delete cascade,
  id                 uuid not null,
  -- Entries logged together by one preset tap share a group, so one undo removes them all.
  group_id           uuid not null,
  kind               text not null check (kind in ('preset', 'quick', 'import')),
  preset_id          uuid,
  -- The preset's name when logged, or 'Quick add'. The day view groups meals by it.
  meal_label         text not null check (length(meal_label) between 1 and 40),
  -- Null leaves room for entries that don't come from the library, such as a photo estimate later.
  food_id            uuid,
  logged_at          timestamptz not null,
  utc_offset_minutes integer not null check (utc_offset_minutes between -840 and 840),
  local_date         date not null,
  quantity           double precision not null check (quantity > 0 and quantity <= 100000),
  unit               text not null,
  base_amount        double precision not null check (base_amount > 0),
  -- The food as it was when logged.
  food_name          text not null,
  food_brand         text,
  base               text not null check (base in ('g', 'ml')),
  nutrients_per_100  jsonb not null check (jsonb_typeof(nutrients_per_100) = 'object'),
  unit_amounts       jsonb not null default '{}'::jsonb check (jsonb_typeof(unit_amounts) = 'object'),
  changed_at         timestamptz not null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz,
  primary key (user_id, id),
  -- A null preset or food skips its check, as foreign keys do.
  foreign key (user_id, preset_id) references food_preset (user_id, id),
  foreign key (user_id, food_id) references food (user_id, id)
);
create index food_log_entry_day on food_log_entry (user_id, local_date, logged_at) where deleted_at is null;
create index food_log_entry_recent on food_log_entry (user_id, food_id, logged_at desc) where deleted_at is null;
create index food_log_entry_group on food_log_entry (user_id, group_id);

-- Targets by day type, each from a date onwards, so changing a target never changes a past day's rings.
create table food_target_set (
  user_id        uuid not null references app_user (id) on delete cascade,
  day_type       text not null check (day_type in ('training', 'rest')),
  effective_from date not null,
  targets        jsonb not null default '{}'::jsonb check (jsonb_typeof(targets) = 'object'),
  changed_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  primary key (user_id, day_type, effective_from)
);

-- A day you've set by hand. A null day_type means you went back to automatic.
create table food_day_type (
  user_id    uuid not null references app_user (id) on delete cascade,
  local_date date not null,
  day_type   text check (day_type in ('training', 'rest')),
  changed_at timestamptz not null,
  updated_at timestamptz not null default now(),
  primary key (user_id, local_date)
);

-- The role food queries run as. It logs in as nobody and skips nothing.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'creed_member') then
    create role creed_member nologin nobypassrls;
  end if;
  -- From Postgres 16, the role that makes another can't switch to it until it grants itself that.
  if current_setting('server_version_num')::int >= 160000 then
    execute format('grant creed_member to %I with set true, inherit false', current_user);
  else
    execute format('grant creed_member to %I', current_user);
  end if;
end
$$;

grant usage on schema public to creed_member;

do $$
declare
  t text;
  r record;
begin
  foreach t in array array['food_nutrient', 'food', 'food_unit', 'food_preset', 'food_preset_item',
                           'food_log_entry', 'food_target_set', 'food_day_type'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('grant select, insert, update, delete on %I to creed_member', t);
    -- The setting is empty outside a food query, which matches nobody.
    execute format('create policy own_rows on %I for all to creed_member '
                   'using (user_id = nullif(current_setting(''creed.user_id'', true), '''')::uuid) '
                   'with check (user_id = nullif(current_setting(''creed.user_id'', true), '''')::uuid)', t);
    for r in select rolname from pg_roles where rolname in ('anon', 'authenticated') loop
      execute format('revoke all on %I from %I', t, r.rolname);
    end loop;
  end loop;
end
$$;
