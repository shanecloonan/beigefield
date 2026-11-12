-- =========================================================================
-- Evidence-based heat: invariant results, heat breakdown, precision
-- =========================================================================
-- Idempotent. Safe to re-apply. Service-role writes only (existing RLS).
-- =========================================================================

alter table if exists public.eth_scan_results
  add column if not exists invariant_results jsonb not null default '[]'::jsonb,
  add column if not exists heat_breakdown jsonb not null default '{}'::jsonb,
  add column if not exists known_safe boolean not null default false,
  add column if not exists contract_name text,
  add column if not exists pattern_leads jsonb not null default '[]'::jsonb,
  add column if not exists hypotheses jsonb not null default '[]'::jsonb;

alter table if exists public.eth_scan_targets
  add column if not exists known_safe boolean not null default false,
  add column if not exists contract_name text,
  add column if not exists heat_breakdown jsonb not null default '{}'::jsonb;

alter table if exists public.test_scan_runs
  add column if not exists invariant_results jsonb not null default '[]'::jsonb,
  add column if not exists heat_breakdown jsonb not null default '{}'::jsonb,
  add column if not exists known_safe boolean not null default false,
  add column if not exists pattern_leads jsonb not null default '[]'::jsonb,
  add column if not exists hypotheses jsonb not null default '[]'::jsonb;

-- Human triage verdict vocabulary used by precision stats on /test.
-- Existing test_triage_events.to_status already stores triage_status values;
-- add an optional verdict_kind for true / false_positive / needs_info.
alter table if exists public.test_triage_events
  add column if not exists verdict_kind text;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'test_triage_events_verdict_kind_check'
  ) then
    alter table public.test_triage_events
      add constraint test_triage_events_verdict_kind_check
      check (
        verdict_kind is null
        or verdict_kind in ('true', 'false_positive', 'needs_info')
      );
  end if;
exception when undefined_table then
  null;
end $$;

create index if not exists test_triage_events_verdict_kind_idx
  on public.test_triage_events (verdict_kind, created_at desc);

create index if not exists test_scan_runs_address_created_idx
  on public.test_scan_runs (address, created_at desc);

-- Precision helper view (flags vs confirmed true). Soft-fail if findings missing.
create or replace view public.test_scan_precision as
select
  count(*) filter (where f.triage_status is not null) as flagged,
  count(*) filter (where f.triage_status in ('human_yes', 'confirmed')) as confirmed_true,
  count(*) filter (where f.triage_status in ('human_no', 'false_positive', 'dismissed')) as confirmed_false,
  count(*) filter (where f.triage_status in ('needs_info', 'reviewing')) as needs_info,
  count(*) filter (where f.triage_status = 'open') as open_flags,
  case
    when count(*) filter (
      where f.triage_status in ('human_yes', 'confirmed', 'human_no', 'false_positive', 'dismissed')
    ) = 0 then null
    else round(
      (
        count(*) filter (where f.triage_status in ('human_yes', 'confirmed'))::numeric
        / nullif(
          count(*) filter (
            where f.triage_status in ('human_yes', 'confirmed', 'human_no', 'false_positive', 'dismissed')
          ),
          0
        )
      ),
      4
    )
  end as precision
from public.test_scan_findings f;
