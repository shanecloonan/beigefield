-- Master-list feed metadata on /test scan runs.
-- discovery_source already exists (recent-deploy migration). Rank order is
-- tier, then USD. Idempotent.

alter table if exists public.test_scan_runs
  add column if not exists candidate_reason text,
  add column if not exists tier integer;

create index if not exists test_scan_runs_discovery_source_idx
  on public.test_scan_runs (discovery_source, created_at desc);

comment on column public.test_scan_runs.candidate_reason is
  'Why this address is on the curated master list (no-audit, upgradeable-proxy, ...).';

comment on column public.test_scan_runs.tier is
  'Master-list priority tier (1 = first). Scan order is tier, then estimated USD.';
