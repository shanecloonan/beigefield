-- Remote history sync: already applied on project soswwsvunulnhlcitpwl.
-- Kept in-repo so Supabase Preview can match remote schema_migrations.

create table if not exists public.ping_tests (
  id bigint generated always as identity primary key,
  note text not null default ''::text,
  created_at timestamptz not null default now()
);

comment on table public.ping_tests is 'Demo table for the Beigefield /supabase test widget';

alter table public.ping_tests enable row level security;

drop policy if exists "anon can insert ping_tests" on public.ping_tests;
create policy "anon can insert ping_tests"
  on public.ping_tests
  for insert
  to anon, authenticated
  with check (true);

drop policy if exists "anon can read ping_tests" on public.ping_tests;
create policy "anon can read ping_tests"
  on public.ping_tests
  for select
  to anon, authenticated
  using (true);

grant select, insert, update, delete, truncate, references, trigger
  on public.ping_tests to anon, authenticated, service_role;
