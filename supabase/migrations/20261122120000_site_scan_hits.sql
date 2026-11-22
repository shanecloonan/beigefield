-- Passive website scan hits. Findings are redacted before insert.
-- Service role writes. The anon key cannot read this table.

create table if not exists public.site_scan_hits (
  id bigint generated always as identity primary key,
  dedupe_key text not null,
  host text not null,
  url text not null,
  heat integer not null default 0,
  peak_heat integer not null default 0,
  score_state text not null default 'provisional',
  pending_stages jsonb not null default '[]'::jsonb,
  findings jsonb not null default '[]'::jsonb,
  heat_breakdown jsonb not null default '{}'::jsonb,
  mode text not null default 'passive',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint site_scan_hits_dedupe_key_unique unique (dedupe_key)
);

create index if not exists site_scan_hits_peak_idx
  on public.site_scan_hits (peak_heat desc, heat desc);

alter table public.site_scan_hits enable row level security;

grant select, insert, update, delete on public.site_scan_hits to service_role;
