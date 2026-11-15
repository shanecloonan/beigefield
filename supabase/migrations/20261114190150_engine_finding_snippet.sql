-- Engine findings are triage evidence. They do not add heat by themselves.
-- `engine` already exists on test_scan_findings; snippet is the short source quote.

alter table if exists public.test_scan_findings
  add column if not exists snippet text;

comment on column public.test_scan_findings.engine is
  'Static/symbolic/fuzz tool that produced this evidence row. Does not add heat.';

comment on column public.test_scan_findings.snippet is
  'Short sanitized source quote. Not an exploit payload.';
