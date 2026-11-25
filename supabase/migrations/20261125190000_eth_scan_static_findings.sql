-- Normalized static-analysis findings (Slither, Aderyn, Semgrep).
-- Evidence rows only. No exploit payloads. Service role writes; no anon read.

create table if not exists public.eth_scan_static_findings (
  id               uuid primary key default gen_random_uuid(),
  chain            text not null default 'ethereum',
  address          text not null
                   check (address ~ '^0x[0-9a-f]{40}$'),
  finding_key      text not null,
  engine           text not null,
  rule             text not null,
  severity         text not null default 'info',
  confidence       text not null default 'low',
  funds_class      text not null default 'other',
  title            text not null default '',
  evidence         text not null default '',
  weight           integer not null default 0,
  counted          boolean not null default false,
  defensive_only   boolean not null default true,
  raw              jsonb not null default '{}'::jsonb,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint eth_scan_static_findings_key unique (chain, address, finding_key)
);

create index if not exists eth_scan_static_findings_address_idx
  on public.eth_scan_static_findings (chain, address, weight desc);

alter table public.eth_scan_static_findings enable row level security;

revoke all on public.eth_scan_static_findings from anon, authenticated;
grant all on public.eth_scan_static_findings to service_role;

comment on table public.eth_scan_static_findings is
  'Sanitized static-analysis evidence. High-confidence detectors carry weight. Not a verdict.';
