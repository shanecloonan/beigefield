-- Phase C protocol graph + risk factors (idempotent)

alter table if exists public.eth_scan_targets
  add column if not exists protocol_graph jsonb not null default '{}'::jsonb,
  add column if not exists protocol_risks jsonb not null default '{}'::jsonb;

alter table if exists public.eth_scan_results
  add column if not exists protocol_graph jsonb not null default '{}'::jsonb,
  add column if not exists protocol_risks jsonb not null default '{}'::jsonb;
