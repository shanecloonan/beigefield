-- =========================================================================
-- Phase B fork / eth_call property results
-- =========================================================================
-- Idempotent. Safe to re-apply.
-- =========================================================================

alter table if exists public.eth_scan_targets
  add column if not exists fork_properties jsonb not null default '[]'::jsonb;

alter table if exists public.eth_scan_results
  add column if not exists fork_properties jsonb not null default '[]'::jsonb;

alter table if exists public.test_scan_runs
  add column if not exists fork_properties jsonb not null default '[]'::jsonb;
