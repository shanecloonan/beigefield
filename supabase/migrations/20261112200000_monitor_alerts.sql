-- Phase F monitor alerts (upgrade / funds-delta). Idempotent.

create table if not exists public.eth_scan_alerts (
  id uuid primary key default gen_random_uuid(),
  address text not null,
  kind text not null check (kind in ('upgrade', 'funds-delta')),
  fingerprint text not null,
  detail text not null default '',
  previous jsonb,
  current jsonb,
  funds_usd numeric,
  created_at timestamptz not null default now(),
  unique (address, fingerprint)
);

create index if not exists eth_scan_alerts_created_idx
  on public.eth_scan_alerts (created_at desc);

create index if not exists eth_scan_alerts_address_idx
  on public.eth_scan_alerts (address, created_at desc);

alter table public.eth_scan_alerts enable row level security;
