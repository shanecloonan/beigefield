-- Chain column for targets and runs. Existing rows become ethereum.
-- Address checks still accept 0x + 40 hex, and also a 32-byte base58
-- account so a later chain can be stored. Ethereum rows are unchanged.

alter table if exists public.eth_scan_targets
  add column if not exists chain text not null default 'ethereum';

alter table if exists public.eth_scan_results
  add column if not exists chain text not null default 'ethereum';

alter table if exists public.eth_scan_artifacts
  add column if not exists chain text not null default 'ethereum';

alter table if exists public.blend_pipeline_stages
  add column if not exists chain text not null default 'ethereum';

create index if not exists eth_scan_targets_chain_status_idx
  on public.eth_scan_targets (chain, status);

create index if not exists test_scan_runs_chain_created_idx
  on public.test_scan_runs (chain, created_at desc);

-- Replace address-shape checks that only allowed 0x. Other checks stay.
do $$
declare r record;
begin
  for r in
    select conrelid::regclass as tbl, conname
    from pg_constraint
    where contype = 'c'
      and connamespace = 'public'::regnamespace
      and conrelid in (
        'public.eth_scan_targets'::regclass,
        'public.eth_scan_artifacts'::regclass,
        'public.eth_scan_results'::regclass,
        'public.test_scan_runs'::regclass,
        'public.test_scan_findings'::regclass
      )
      and pg_get_constraintdef(oid) ilike '%0x%'
      and pg_get_constraintdef(oid) not ilike '%kind%'
  loop
    execute format('alter table %s drop constraint %I', r.tbl, r.conname);
  end loop;
end $$;

alter table public.eth_scan_targets
  drop constraint if exists eth_scan_targets_address_check;
alter table public.eth_scan_targets
  add constraint eth_scan_targets_address_check
  check (
    address ~ '^0x[0-9a-f]{40}$'
    or address ~ '^[1-9A-HJ-NP-Za-km-z]{32,44}$'
  );

alter table public.eth_scan_artifacts
  drop constraint if exists eth_scan_artifacts_address_check;
alter table public.eth_scan_artifacts
  add constraint eth_scan_artifacts_address_check
  check (
    address ~ '^0x[0-9a-f]{40}$'
    or address ~ '^[1-9A-HJ-NP-Za-km-z]{32,44}$'
  );

alter table public.eth_scan_results
  drop constraint if exists eth_scan_results_address_check;
alter table public.eth_scan_results
  add constraint eth_scan_results_address_check
  check (
    address ~ '^0x[0-9a-f]{40}$'
    or address ~ '^[1-9A-HJ-NP-Za-km-z]{32,44}$'
  );

alter table public.test_scan_runs
  drop constraint if exists test_scan_runs_address_check;
alter table public.test_scan_runs
  add constraint test_scan_runs_address_check
  check (
    address is null
    or address ~ '^0x[0-9a-f]{40}$'
    or address ~ '^[1-9A-HJ-NP-Za-km-z]{32,44}$'
  );

alter table public.test_scan_findings
  drop constraint if exists test_scan_findings_address_check;
alter table public.test_scan_findings
  add constraint test_scan_findings_address_check
  check (
    address is null
    or address ~ '^0x[0-9a-f]{40}$'
    or address ~ '^[1-9A-HJ-NP-Za-km-z]{32,44}$'
  );
