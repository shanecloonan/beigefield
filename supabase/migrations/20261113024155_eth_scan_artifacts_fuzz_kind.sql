-- Allow defensive fuzz proof artifacts (property failures / reproductions).
-- kind='fuzz' is proof of a bug for /test review — never an attack payload.

alter table public.eth_scan_artifacts
  drop constraint if exists eth_scan_artifacts_kind_check;

alter table public.eth_scan_artifacts
  add constraint eth_scan_artifacts_kind_check
  check (kind in ('source', 'decompile', 'ir', 'report', 'fuzz'));
