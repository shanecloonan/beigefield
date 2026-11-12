-- Recent-deployment discovery age fields + drop_reason clarity.
-- Idempotent. Prefer newest deployments when claiming the queue.

alter table if exists public.eth_scan_targets
  add column if not exists deployed_block bigint,
  add column if not exists deployed_at timestamptz,
  add column if not exists discovery_source text;

alter table if exists public.eth_scan_results
  add column if not exists deployed_block bigint,
  add column if not exists deployed_at timestamptz,
  add column if not exists discovery_source text,
  add column if not exists drop_reason text;

alter table if exists public.test_scan_runs
  add column if not exists deployed_block bigint,
  add column if not exists deployed_at timestamptz,
  add column if not exists discovery_source text;

create index if not exists eth_scan_targets_deployed_block_idx
  on public.eth_scan_targets (deployed_block desc nulls last);

create index if not exists eth_scan_targets_pending_deployed_idx
  on public.eth_scan_targets (status, deployed_block desc nulls last)
  where status = 'pending';

create index if not exists test_scan_runs_deployed_block_idx
  on public.test_scan_runs (deployed_block desc nulls last);
