-- =========================================================================
-- Phase A deep engines: agreement findings on queue targets / results
-- =========================================================================
-- Idempotent. Safe to re-apply. Service-role writes only (existing RLS).
-- =========================================================================

alter table if exists public.eth_scan_targets
  add column if not exists deep_status text,
  add column if not exists engine_findings jsonb not null default '[]'::jsonb,
  add column if not exists engine_agreement jsonb not null default '{}'::jsonb;

alter table if exists public.eth_scan_results
  add column if not exists engine_findings jsonb not null default '[]'::jsonb,
  add column if not exists engine_agreement jsonb not null default '{}'::jsonb;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'eth_scan_targets_deep_status_check'
  ) then
    alter table public.eth_scan_targets
      add constraint eth_scan_targets_deep_status_check
      check (
        deep_status is null
        or deep_status in ('pending', 'running', 'done', 'skipped', 'error')
      );
  end if;
exception when undefined_table then
  null;
end $$;

create index if not exists eth_scan_targets_deep_claim_idx
  on public.eth_scan_targets (bucket, deep_status, updated_at asc)
  where bucket in ('lane-b-queue', 'manual-review');
