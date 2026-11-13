-- Phase-G defensive artifact kinds: symbolic / oracle / admin / storage / clone.
-- Proof or evidence only — never attack payloads.

alter table public.eth_scan_artifacts
  drop constraint if exists eth_scan_artifacts_kind_check;

alter table public.eth_scan_artifacts
  add constraint eth_scan_artifacts_kind_check
  check (kind in (
    'source',
    'decompile',
    'ir',
    'report',
    'fuzz',
    'symbolic',
    'oracle',
    'admin',
    'storage',
    'clone'
  ));
