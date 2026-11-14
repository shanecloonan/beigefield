-- Per-rule triage precision. Engine rows are evidence; this view only counts
-- how often humans mark a rule true or false. It does not change heat.

create or replace view public.test_scan_rule_precision as
select
  coalesce(nullif(f.rule, ''), nullif(f.detector, ''), 'unknown') as rule,
  coalesce(nullif(f.engine, ''), 'unknown') as engine,
  count(*)::bigint as fires,
  count(*) filter (where f.triage_status in ('human_yes', 'confirmed'))::bigint as triaged_true,
  count(*) filter (where f.triage_status in ('human_no', 'false_positive', 'dismissed'))::bigint as triaged_false,
  count(*) filter (where f.triage_status = 'open')::bigint as open_flags
from public.test_scan_findings f
group by 1, 2;

comment on view public.test_scan_rule_precision is
  'Fires and human true/false marks per rule. Noisy rules stay visible.';
