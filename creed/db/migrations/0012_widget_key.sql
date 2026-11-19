-- A read-only key for a home screen widget (the Scriptable app on iPhone), which can't sign in with a passkey.
-- It reads only today's food totals against targets. One per person; making a new one replaces the old.
-- Stored as a hash, like sessions, so the database never holds the key itself. Only the server reads this.
create table widget_key (
  user_id      uuid primary key references app_user (id) on delete cascade,
  key_hash     bytea not null unique,
  created_at   timestamptz not null default now(),
  last_used_at timestamptz
);

do $$
declare
  r record;
begin
  alter table widget_key enable row level security;
  alter table widget_key force row level security;
  for r in select rolname from pg_roles where rolname in ('anon', 'authenticated') loop
    execute format('revoke all on widget_key from %I', r.rolname);
  end loop;
end
$$;
