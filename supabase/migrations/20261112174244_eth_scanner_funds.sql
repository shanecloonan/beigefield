-- ============================================================================
-- Live funds floor fields for eth_scan_* + test_scan_*
-- ============================================================================
-- Idempotent. Safe to re-apply. Service-role writes only (existing RLS).
-- ============================================================================

alter table if exists public.eth_scan_targets
  add column if not exists funds_usd numeric,
  add column if not exists funds_breakdown jsonb not null default '[]'::jsonb,
  add column if not exists funds_status text,
  add column if not exists funds_checked_at timestamptz;

alter table if exists public.eth_scan_results
  add column if not exists funds_usd numeric,
  add column if not exists funds_breakdown jsonb not null default '[]'::jsonb,
  add column if not exists funds_status text,
  add column if not exists funds_checked_at timestamptz;

create index if not exists eth_scan_targets_funds_usd_idx
  on public.eth_scan_targets (funds_usd);

create index if not exists eth_scan_results_funds_usd_idx
  on public.eth_scan_results (funds_usd);

alter table if exists public.test_scan_runs
  add column if not exists funds_usd numeric,
  add column if not exists funds_breakdown jsonb not null default '[]'::jsonb,
  add column if not exists funds_status text,
  add column if not exists funds_checked_at timestamptz;

create index if not exists test_scan_runs_funds_usd_idx
  on public.test_scan_runs (funds_usd);
