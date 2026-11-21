-- Key eth_scan_targets by (chain, address).
-- Existing rows already have chain default 'ethereum'. Their addresses
-- are not rewritten and no row is deleted. Artifacts and results take
-- the chain of the target they already point at, while address is still
-- unique, then follow the new key.

alter table if exists public.eth_scan_targets
  add column if not exists chain text not null default 'ethereum';

alter table if exists public.eth_scan_results
  add column if not exists chain text not null default 'ethereum';

alter table if exists public.eth_scan_artifacts
  add column if not exists chain text not null default 'ethereum';

update public.eth_scan_targets
  set chain = 'ethereum'
  where chain is null;

update public.eth_scan_artifacts as artifact
  set chain = target.chain
  from public.eth_scan_targets as target
  where artifact.address = target.address
    and artifact.chain is distinct from target.chain;

update public.eth_scan_results as result
  set chain = target.chain
  from public.eth_scan_targets as target
  where result.address = target.address
    and result.chain is distinct from target.chain;

do $$
declare fk record;
begin
  for fk in
    select con.conname, con.conrelid::regclass as tbl
    from pg_constraint as con
    join pg_class as rel on rel.oid = con.confrelid
    where con.contype = 'f'
      and rel.relname = 'eth_scan_targets'
      and con.connamespace = 'public'::regnamespace
  loop
    execute format('alter table %s drop constraint %I', fk.tbl, fk.conname);
  end loop;
end $$;

do $$
declare pk record;
begin
  for pk in
    select conname
    from pg_constraint
    where contype = 'p'
      and conrelid = 'public.eth_scan_targets'::regclass
  loop
    execute format('alter table public.eth_scan_targets drop constraint %I', pk.conname);
  end loop;
end $$;

alter table public.eth_scan_targets
  add constraint eth_scan_targets_pkey primary key (chain, address);

alter table public.eth_scan_artifacts
  drop constraint if exists eth_scan_artifacts_target_fkey;

alter table public.eth_scan_artifacts
  add constraint eth_scan_artifacts_target_fkey
  foreign key (chain, address)
  references public.eth_scan_targets (chain, address)
  on delete cascade;

alter table public.eth_scan_results
  drop constraint if exists eth_scan_results_target_fkey;

alter table public.eth_scan_results
  add constraint eth_scan_results_target_fkey
  foreign key (chain, address)
  references public.eth_scan_targets (chain, address)
  on delete cascade;
