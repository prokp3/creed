-- Passkey sign-in. One deployment, one person, so there is no user table.
-- Session tokens and the recovery code are stored only as hashes, so a copy of this database can't sign in.
create table auth_credential (
  credential_id bytea primary key,
  public_key    bytea not null,
  sign_count    bigint not null default 0,
  backed_up     boolean not null default false,
  label         text not null,
  created_at    timestamptz not null default now(),
  last_used_at  timestamptz
);

-- A challenge is used once. It's deleted when an answer arrives, whether or not the answer is good.
create table auth_challenge (
  challenge  bytea primary key,
  purpose    text not null check (purpose in ('register', 'sign_in')),
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);
create index auth_challenge_purpose on auth_challenge (purpose, created_at);

create table auth_session (
  token_hash   bytea primary key,
  kind         text not null check (kind in ('passkey', 'recovery', 'dev')),
  created_at   timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  expires_at   timestamptz not null
);

-- At most one row: the code that works right now. Using it deletes it.
create table auth_recovery_code (
  code_hash  bytea primary key,
  created_at timestamptz not null default now()
);

alter table auth_credential enable row level security;
alter table auth_challenge enable row level security;
alter table auth_session enable row level security;
alter table auth_recovery_code enable row level security;

do $$
declare
  r record;
begin
  for r in select rolname from pg_roles where rolname in ('anon', 'authenticated') loop
    execute format('revoke all on auth_credential, auth_challenge, auth_session, auth_recovery_code from %I', r.rolname);
  end loop;
end
$$;
