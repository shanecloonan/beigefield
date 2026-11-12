-- Worker posts contract_class to eth_scan_results; column was missing (PGRST204).
alter table if exists public.eth_scan_results
  add column if not exists contract_class text,
  add column if not exists funds_rank numeric;
notify pgrst, 'reload schema';
