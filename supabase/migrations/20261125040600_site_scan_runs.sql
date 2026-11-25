-- One row per site-scanner run. Counts only. No page bodies and no secrets.
-- Service role writes. The anon key cannot read this table.

create table if not exists public.site_scan_runs (
  id bigint generated always as identity primary key,
  run_id text not null,
  started_at timestamptz not null,
  finished_at timestamptz,
  hosts_scanned integer not null default 0,
  finding_count integer not null default 0,
  created_at timestamptz not null default now(),
  constraint site_scan_runs_run_id_unique unique (run_id),
  constraint site_scan_runs_hosts_nonnegative check (hosts_scanned >= 0),
  constraint site_scan_runs_findings_nonnegative check (finding_count >= 0)
);

create index if not exists site_scan_runs_started_idx
  on public.site_scan_runs (started_at desc);

alter table public.site_scan_runs enable row level security;

grant select, insert, update, delete on public.site_scan_runs to service_role;
