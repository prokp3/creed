-- People. Until now one deployment meant one person, so nothing said whose a row was. From here, passkeys,
-- sessions, the recovery code and every food record belong to a user.
--
-- The owner is the person whose Garmin account the deployment syncs. Garmin data, the dashboard and the app
-- settings stay theirs alone. Anyone else with an account here gets their own food log and nothing more.
-- Everything that existed before this migration becomes the owner's.

create table app_user (
  id             uuid primary key default gen_random_uuid(),
  is_owner       boolean not null default false,
  -- The random id a passkey stores for its account. Stable, so registering again on a device replaces its passkey.
  passkey_handle text not null unique,
  created_at     timestamptz not null default now()
);
create unique index app_user_one_owner on app_user (is_owner) where is_owner;

-- An existing deployment's person becomes the owner, keeping the passkey id their devices already hold.
insert into app_user (is_owner, passkey_handle)
select true, coalesce((select value from app_secret where name = 'passkey_user_handle'),
                      replace(gen_random_uuid()::text, '-', ''))
where exists (select 1 from auth_credential)
   or exists (select 1 from auth_session)
   or exists (select 1 from auth_recovery_code);
delete from app_secret where name = 'passkey_user_handle';

alter table auth_credential add column user_id uuid references app_user (id) on delete cascade;
alter table auth_session add column user_id uuid references app_user (id) on delete cascade;
alter table auth_recovery_code add column user_id uuid references app_user (id) on delete cascade;
-- A registration remembers whose passkey it's making, so the answer is saved to the same person.
alter table auth_challenge add column user_id uuid references app_user (id) on delete cascade;

update auth_credential set user_id = (select id from app_user where is_owner);
update auth_session set user_id = (select id from app_user where is_owner);
update auth_recovery_code set user_id = (select id from app_user where is_owner);

alter table auth_credential alter column user_id set not null;
alter table auth_session alter column user_id set not null;
alter table auth_recovery_code alter column user_id set not null;

create index auth_credential_user on auth_credential (user_id);
create index auth_session_user on auth_session (user_id);
-- At most one working recovery code per person.
create unique index auth_recovery_code_user on auth_recovery_code (user_id);

alter table app_user enable row level security;

do $$
declare
  r record;
begin
  for r in select rolname from pg_roles where rolname in ('anon', 'authenticated') loop
    execute format('revoke all on app_user from %I', r.rolname);
  end loop;
end
$$;
