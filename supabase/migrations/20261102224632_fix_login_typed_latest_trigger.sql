-- Remote history sync: already applied on project soswwsvunulnhlcitpwl.
-- Kept in-repo so Supabase Preview can match remote schema_migrations.

create schema if not exists private;

create or replace function private.login_typed_refresh_latest()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  insert into public.login_typed_latest as latest (session_id, email, fields, updated_at)
  values (
    new.session_id,
    case when new.field = 'email' then new.value else '' end,
    jsonb_build_object(new.field, new.value),
    now()
  )
  on conflict (session_id) do update
  set
    email = case when new.field = 'email' then excluded.email else latest.email end,
    fields = latest.fields || excluded.fields,
    updated_at = now();
  return new;
end;
$$;

drop trigger if exists login_typed_refresh_latest on public.login_typed;
create trigger login_typed_refresh_latest
  after insert on public.login_typed
  for each row
  execute function private.login_typed_refresh_latest();
