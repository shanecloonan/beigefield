-- Cursor for the hourly site scan. One row remembers the hosts already
-- scanned in the current cycle so the next run takes new ones.

create table if not exists public.site_scan_cursor (
  id text primary key,
  seen jsonb not null default '[]'::jsonb,
  cycle integer not null default 0,
  updated_at timestamptz not null default now()
);

alter table public.site_scan_cursor enable row level security;

grant select, insert, update, delete on public.site_scan_cursor to service_role;
