-- Checkpointed mainnet contract-create backfill (30d / custom window).
-- cursor_block is the last block processed (inclusive). Resumes across jobs.

create table if not exists public.eth_scan_backfill (
  id text primary key,
  start_block bigint not null,
  end_block bigint not null,
  cursor_block bigint not null,
  status text not null default 'running',
  -- running | done | error
  source text,
  discovered bigint not null default 0,
  deduped bigint not null default 0,
  funds_ge_floor bigint not null default 0,
  funds_below_floor bigint not null default 0,
  funds_unknown bigint not null default 0,
  fully_scanned bigint not null default 0,
  heat_positive bigint not null default 0,
  last_error text,
  stats jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.eth_scan_backfill is
  'Checkpointed contract-create backfill; cursor_block is last processed inclusive.';
