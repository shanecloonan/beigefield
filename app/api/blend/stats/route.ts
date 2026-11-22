/**
 * Aggregate Blend desk stats. Read-only.
 * One finished scan per address: scanned total, Yes / Maybe / No, top heat.
 */

import { NextResponse } from "next/server";
import { DEFAULT_CHAIN, LEADERBOARD_LIMIT, normalizeChain, summarizeBlendRuns, type BlendRunLike } from "@/lib/eth-scanner/blend-board";
import { createServiceSupabaseClient } from "@/lib/eth-scanner/service-supabase";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const PAGE = 1000;
const MAX_ROWS = 20_000;
const HOT_LIMIT = 500;

const COLUMN_SETS = [
  "chain,address,heat,blend_heat,blend_bucket,bucket,funds_usd,tvl_usd,money_at_risk_usd,contract_name,created_at,status,heat_breakdown,notes,drop_reason",
  "address,heat,blend_heat,blend_bucket,bucket,funds_usd,tvl_usd,money_at_risk_usd,contract_name,created_at,status,heat_breakdown,notes,drop_reason",
  "address,heat,bucket,funds_usd,tvl_usd,money_at_risk_usd,contract_name,created_at,status,heat_breakdown,notes,drop_reason",
  "address,heat,bucket,created_at,status,heat_breakdown,notes,drop_reason",
];

function scanIdentity(row: BlendRunLike): string {
  return [
    normalizeChain(row.chain),
    String(row.address || "").trim().toLowerCase(),
    String(row.created_at || ""),
    String(row.heat ?? ""),
    String(row.blend_heat ?? ""),
    String(row.status || ""),
    String(row.blend_bucket || ""),
    String(row.bucket || ""),
  ].join("|");
}

/** The hot-heat query repeats rows already on the recent page. Count each scan once. */
function uniqueScans(rows: BlendRunLike[]): BlendRunLike[] {
  const seen = new Set<string>();
  const out: BlendRunLike[] = [];
  for (const row of rows) {
    const key = scanIdentity(row);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(row);
  }
  return out;
}

function json(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" },
  });
}

function empty(connected: boolean, chain = DEFAULT_CHAIN) {
  const board = summarizeBlendRuns([], LEADERBOARD_LIMIT, Date.now(), chain);
  return json({
    ok: true,
    connected,
    chain: board.chain,
    truncated: false,
    scanned: board.scanned,
    totals: board.totals,
    leaderboard: board.leaderboard,
    flagged: board.flagged,
    requeue: board.requeue,
  });
}

async function loadColumns(
  sb: NonNullable<ReturnType<typeof createServiceSupabaseClient>>,
): Promise<{ columns: string; rows: BlendRunLike[]; truncated: boolean }> {
  let columns = COLUMN_SETS[0];
  const rows: BlendRunLike[] = [];
  let from = 0;
  let truncated = false;
  while (from < MAX_ROWS) {
    const { data, error } = await sb
      .from("test_scan_runs")
      .select(columns)
      .order("created_at", { ascending: false })
      .range(from, from + PAGE - 1);
    if (error) {
      const next = COLUMN_SETS[COLUMN_SETS.indexOf(columns) + 1];
      if (next && /column|schema cache/i.test(error.message || "")) {
        columns = next;
        rows.length = 0;
        from = 0;
        continue;
      }
      break;
    }
    const page = (data ?? []) as BlendRunLike[];
    rows.push(...page);
    if (page.length < PAGE) break;
    from += PAGE;
    if (from >= MAX_ROWS) truncated = true;
  }
  return { columns, rows, truncated };
}

export async function GET(request: Request) {
  const requested = normalizeChain(new URL(request.url).searchParams.get("chain") || DEFAULT_CHAIN);
  const sb = createServiceSupabaseClient();
  if (!sb) return empty(false, requested);
  try {
    const loaded = await loadColumns(sb);
    let rows = loaded.rows;
    const hot = await sb
      .from("test_scan_runs")
      .select(loaded.columns)
      .order("heat", { ascending: false })
      .limit(HOT_LIMIT);
    if (!hot.error && hot.data) rows = rows.concat(hot.data as BlendRunLike[]);
    if (loaded.columns.includes("blend_heat")) {
      const hotBlend = await sb
        .from("test_scan_runs")
        .select(loaded.columns)
        .order("blend_heat", { ascending: false })
        .limit(HOT_LIMIT);
      if (!hotBlend.error && hotBlend.data) rows = rows.concat(hotBlend.data as BlendRunLike[]);
    }
    const board = summarizeBlendRuns(uniqueScans(rows), LEADERBOARD_LIMIT, Date.now(), requested);
    return json({
      ok: true,
      connected: true,
      chain: board.chain,
      truncated: loaded.truncated,
      scanned: board.scanned,
      totals: board.totals,
      leaderboard: board.leaderboard,
      flagged: board.flagged,
      requeue: board.requeue,
    });
  } catch {
    return empty(true, requested);
  }
}
