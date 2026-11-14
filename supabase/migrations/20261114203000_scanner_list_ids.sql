-- Per-list identity on /test scan runs, plus addresses added from the desk.
-- Existing master-list rows belong to List 1. Idempotent.

alter table if exists public.test_scan_runs
  add column if not exists list_id text,
  add column if not exists list_name text;

update public.test_scan_runs
set list_id = 'list-1',
    list_name = 'List 1'
where list_id is null
  and discovery_source = 'master_list';

create index if not exists test_scan_runs_list_created_idx
  on public.test_scan_runs (list_id, created_at desc);

comment on column public.test_scan_runs.list_id is
  'Named master list this run belongs to (list-1, list-2). Null legacy master_list rows are List 1.';

comment on column public.test_scan_runs.list_name is
  'Display name of the master list at scan time.';

create table if not exists public.scanner_list_addresses (
  list_id text not null,
  address text not null
    check (address ~ '^0x[0-9a-f]{40}$'),
  created_at timestamptz not null default now(),
  primary key (list_id, address)
);

alter table public.scanner_list_addresses enable row level security;

comment on table public.scanner_list_addresses is
  'Addresses added to a named master list from /test. Service role only. Merged with eth-scanner/data/lists/manual.json.';
