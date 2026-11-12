-- ============================================================================
-- /test desk — detailed scan runs, findings, and triage history
-- ============================================================================
--
-- Persists every result the ETH invariant scanner /test page produces
-- (Lane A, research stack, multi-engine desk / paste normalize), including
-- severity, funds-at-risk class, TVL / money-at-risk, receipts, and a full
-- raw jsonb payload. Triage status changes are append-only events.
--
-- Writes: service_role only (server routes). RLS enabled; anon/authenticated
-- have no privileges. Idempotent — safe to re-apply (IF NOT EXISTS).
-- ============================================================================

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- Scan runs (one row per /test invocation)
-- ---------------------------------------------------------------------------

create table if not exists public.test_scan_runs (
  id                 uuid primary key default gen_random_uuid(),
  -- Stable upsert key so retries / double-posts do not duplicate a run.
  dedupe_key         text not null,
  kind               text not null
                     check (kind in ('lane-a', 'research', 'engines', 'engines-paste')),
  chain              text not null default 'ethereum',
  address            text
                     check (address is null or address ~ '^0x[0-9a-f]{40}$'),
  fixture            text,
  contract_name      text,
  bytecode_hash      text,
  tvl_usd            numeric,
  money_at_risk_usd  numeric,
  bucket             text
                     check (bucket is null or bucket in (
                       'lane-a-cool',
                       'lane-b-queue',
                       'manual-review',
                       'human-no-candidate',
                       'human-yes-candidate'
                     )),
  heat               integer,
  status             text not null default 'done'
                     check (status in ('pending', 'running', 'done', 'dropped', 'error', 'gated')),
  dropped            boolean not null default false,
  drop_reason        text,
  src_confidence     text check (src_confidence is null or src_confidence in ('high', 'med', 'low')),
  ir_confidence      text check (ir_confidence is null or ir_confidence in ('high', 'med', 'low')),
  contract_class     text,
  scope              text,
  value_movers       jsonb not null default '[]'::jsonb,
  stage_trace        jsonb not null default '[]'::jsonb,
  hypotheses         jsonb not null default '[]'::jsonb,
  pattern_leads      jsonb not null default '[]'::jsonb,
  layers_run         jsonb not null default '[]'::jsonb,
  layers_skipped     jsonb not null default '[]'::jsonb,
  engines            jsonb not null default '[]'::jsonb,
  severity_counts    jsonb not null default '{}'::jsonb,
  findings_count     integer not null default 0,
  notes              jsonb not null default '[]'::jsonb,
  receipt_filename   text,
  receipt_markdown   text,
  duration_ms        integer,
  dry_run            boolean,
  live_ingest        boolean,
  persist_remote     boolean,
  error              text,
  -- Full API / CLI payload for this run (lossy columns above are convenience).
  raw                jsonb not null default '{}'::jsonb,
  started_at         timestamptz not null default now(),
  finished_at        timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint test_scan_runs_dedupe_key_unique unique (dedupe_key)
);

create index if not exists test_scan_runs_kind_created_idx
  on public.test_scan_runs (kind, created_at desc);

create index if not exists test_scan_runs_address_created_idx
  on public.test_scan_runs (address, created_at desc);

create index if not exists test_scan_runs_bucket_created_idx
  on public.test_scan_runs (bucket, created_at desc);

create index if not exists test_scan_runs_status_created_idx
  on public.test_scan_runs (status, created_at desc);

create index if not exists test_scan_runs_raw_gin_idx
  on public.test_scan_runs using gin (raw);

-- ---------------------------------------------------------------------------
-- Findings / results (one row per finding; Lane A may have zero findings)
-- ---------------------------------------------------------------------------

create table if not exists public.test_scan_findings (
  id                 uuid primary key default gen_random_uuid(),
  run_id             uuid not null
                     references public.test_scan_runs (id) on delete cascade,
  -- Stable within a run (engine:rule:file:line or research finding id).
  finding_key        text not null,
  kind               text not null
                     check (kind in ('lane-a', 'research', 'engines', 'engines-paste', 'hypothesis')),
  address            text
                     check (address is null or address ~ '^0x[0-9a-f]{40}$'),
  chain              text not null default 'ethereum',
  engine             text,
  detector           text,
  rule               text,
  layer              text,
  title              text not null default '',
  severity           text
                     check (severity is null or severity in (
                       'critical', 'crit', 'high', 'medium', 'med', 'low', 'info'
                     )),
  confidence         text
                     check (confidence is null or confidence in ('high', 'medium', 'med', 'low')),
  funds_at_risk_class text,
  triage_score       integer,
  triage_status      text not null default 'open'
                     check (triage_status in (
                       'open',
                       'reviewing',
                       'confirmed',
                       'dismissed',
                       'false_positive',
                       'human_yes',
                       'human_no'
                     )),
  invariant_text     text,
  hypothesis_status  text
                     check (hypothesis_status is null or hypothesis_status in ('HOLDS', 'BROKEN', 'OPEN')),
  locus              text,
  location_file      text,
  location_line      integer,
  location_contract  text,
  location_function  text,
  evidence           text,
  references_json    jsonb not null default '[]'::jsonb,
  axes               jsonb not null default '[]'::jsonb,
  tvl_usd            numeric,
  money_at_risk_usd  numeric,
  defensive_only     boolean not null default true,
  notes              jsonb not null default '[]'::jsonb,
  raw                jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint test_scan_findings_run_key_unique unique (run_id, finding_key)
);

create index if not exists test_scan_findings_run_idx
  on public.test_scan_findings (run_id, created_at desc);

create index if not exists test_scan_findings_address_idx
  on public.test_scan_findings (address, created_at desc);

create index if not exists test_scan_findings_severity_idx
  on public.test_scan_findings (severity, triage_status, created_at desc);

create index if not exists test_scan_findings_triage_status_idx
  on public.test_scan_findings (triage_status, created_at desc);

create index if not exists test_scan_findings_class_idx
  on public.test_scan_findings (funds_at_risk_class, created_at desc);

create index if not exists test_scan_findings_raw_gin_idx
  on public.test_scan_findings using gin (raw);

-- ---------------------------------------------------------------------------
-- Triage events (append-only status history)
-- ---------------------------------------------------------------------------

create table if not exists public.test_triage_events (
  id                 uuid primary key default gen_random_uuid(),
  finding_id         uuid not null
                     references public.test_scan_findings (id) on delete cascade,
  run_id             uuid
                     references public.test_scan_runs (id) on delete set null,
  from_status        text,
  to_status          text not null
                     check (to_status in (
                       'open',
                       'reviewing',
                       'confirmed',
                       'dismissed',
                       'false_positive',
                       'human_yes',
                       'human_no'
                     )),
  actor              text not null default 'desk',
  note               text,
  raw                jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now()
);

create index if not exists test_triage_events_finding_idx
  on public.test_triage_events (finding_id, created_at desc);

create index if not exists test_triage_events_run_idx
  on public.test_triage_events (run_id, created_at desc);

create index if not exists test_triage_events_to_status_idx
  on public.test_triage_events (to_status, created_at desc);

-- ---------------------------------------------------------------------------
-- updated_at touch triggers
-- ---------------------------------------------------------------------------

create or replace function public.test_scan_touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists test_scan_runs_touch on public.test_scan_runs;
create trigger test_scan_runs_touch
  before update on public.test_scan_runs
  for each row
  execute function public.test_scan_touch_updated_at();

drop trigger if exists test_scan_findings_touch on public.test_scan_findings;
create trigger test_scan_findings_touch
  before update on public.test_scan_findings
  for each row
  execute function public.test_scan_touch_updated_at();

-- Log triage_status changes automatically -----------------------------------

create or replace function public.test_scan_log_triage_status()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'UPDATE' and new.triage_status is distinct from old.triage_status then
    insert into public.test_triage_events (finding_id, run_id, from_status, to_status, actor, note, raw)
    values (
      new.id,
      new.run_id,
      old.triage_status,
      new.triage_status,
      coalesce(current_setting('app.triage_actor', true), 'desk'),
      coalesce(current_setting('app.triage_note', true), null),
      jsonb_build_object('source', 'trigger')
    );
  elsif tg_op = 'INSERT' then
    insert into public.test_triage_events (finding_id, run_id, from_status, to_status, actor, note, raw)
    values (
      new.id,
      new.run_id,
      null,
      new.triage_status,
      'system',
      'initial',
      jsonb_build_object('source', 'insert')
    );
  end if;
  return new;
end;
$$;

drop trigger if exists test_scan_findings_triage_log on public.test_scan_findings;
create trigger test_scan_findings_triage_log
  after insert or update of triage_status on public.test_scan_findings
  for each row
  execute function public.test_scan_log_triage_status();

-- ---------------------------------------------------------------------------
-- RLS: no anon/authenticated access. Service role bypasses RLS.
-- ---------------------------------------------------------------------------

alter table public.test_scan_runs enable row level security;
alter table public.test_scan_findings enable row level security;
alter table public.test_triage_events enable row level security;

revoke all on public.test_scan_runs from anon, authenticated;
revoke all on public.test_scan_findings from anon, authenticated;
revoke all on public.test_triage_events from anon, authenticated;

grant all on public.test_scan_runs to service_role;
grant all on public.test_scan_findings to service_role;
grant all on public.test_triage_events to service_role;
