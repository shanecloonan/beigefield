-- Blend ensemble journal.
-- One row per blend run on public.test_scan_runs (kind = 'blend'), plus one
-- row per stage in public.blend_pipeline_stages so a crash mid-run keeps the
-- stages that already committed. Idempotent.

alter table if exists public.test_scan_runs
  add column if not exists blend_bucket text,
  add column if not exists blend_heat integer,
  add column if not exists proven_caller_profit boolean,
  add column if not exists evidence_only boolean,
  add column if not exists drain_probability numeric,
  add column if not exists agreement_score numeric,
  add column if not exists engines_agreeing jsonb not null default '[]'::jsonb,
  add column if not exists bug_classes jsonb not null default '[]'::jsonb,
  add column if not exists blend_receipt jsonb not null default '{}'::jsonb;

-- Widen kind so blend runs share the existing table. Keep the lane buckets
-- on `bucket`; blend's drain-found / maybe / no lives in blend_bucket.
do $$
declare r record;
begin
  for r in
    select conname
    from pg_constraint
    where conrelid = 'public.test_scan_runs'::regclass
      and contype = 'c'
      and pg_get_constraintdef(oid) ilike '%kind%'
      and pg_get_constraintdef(oid) ilike '%lane-a%'
  loop
    execute format('alter table public.test_scan_runs drop constraint %I', r.conname);
  end loop;
end $$;

alter table public.test_scan_runs
  drop constraint if exists test_scan_runs_kind_check;

alter table public.test_scan_runs
  add constraint test_scan_runs_kind_check
  check (kind in ('lane-a', 'research', 'engines', 'engines-paste', 'blend'));

do $$
declare r record;
begin
  for r in
    select conname
    from pg_constraint
    where conrelid = 'public.test_scan_findings'::regclass
      and contype = 'c'
      and pg_get_constraintdef(oid) ilike '%kind%'
      and pg_get_constraintdef(oid) ilike '%hypothesis%'
  loop
    execute format('alter table public.test_scan_findings drop constraint %I', r.conname);
  end loop;
end $$;

alter table public.test_scan_findings
  drop constraint if exists test_scan_findings_kind_check;

alter table public.test_scan_findings
  add constraint test_scan_findings_kind_check
  check (kind in ('lane-a', 'research', 'engines', 'engines-paste', 'hypothesis', 'blend'));

create table if not exists public.blend_pipeline_stages (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references public.test_scan_runs (id) on delete cascade,
  dedupe_key text not null,
  address text,
  stage text not null,
  status text not null default 'ok',
  heat_contribution integer not null default 0,
  bug_classes jsonb not null default '[]'::jsonb,
  payload jsonb not null default '{}'::jsonb,
  error text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  constraint blend_pipeline_stages_dedupe_stage unique (dedupe_key, stage)
);

create index if not exists blend_pipeline_stages_run_idx
  on public.blend_pipeline_stages (run_id, created_at desc);

create index if not exists blend_pipeline_stages_address_idx
  on public.blend_pipeline_stages (address, created_at desc);

alter table public.blend_pipeline_stages enable row level security;

revoke all on public.blend_pipeline_stages from anon, authenticated;
grant all on public.blend_pipeline_stages to service_role;

comment on table public.blend_pipeline_stages is
  'One row per Blend pipeline stage. Written as the stage finishes so a crash keeps the trail.';

comment on column public.test_scan_runs.blend_bucket is
  'Blend decision: drain-found, maybe, or no. Lane A/B buckets stay in bucket.';

comment on column public.test_scan_runs.proven_caller_profit is
  'True only when the caller-profit gate proved an unprivileged balance rise.';

comment on column public.test_scan_runs.blend_receipt is
  'Unified deduped Blend receipt (findings, layers, heat breakdown).';
