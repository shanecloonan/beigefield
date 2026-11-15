/**
 * Live view of the automatic scan cycle. Read-only.
 * The monitor and backfill jobs own the loop. This route does not start it.
 */

import { NextResponse } from "next/server";
import { classifyOutcome, loadMasterLists, normalizeAddress, runMatchesList } from "@/lib/eth-scanner/lists";
import { createServiceSupabaseClient } from "@/lib/eth-scanner/service-supabase";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function json(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" },
  });
}

type RunRow = {
  address?: string;
  bucket?: string;
  heat?: number;
  discovery_source?: string;
  list_id?: string;
  dedupe_key?: string;
  created_at?: string;
  notes?: unknown;
  heat_breakdown?: unknown;
};

export async function GET() {
  const loaded = loadMasterLists();
  const sb = createServiceSupabaseClient();
  let cycle: { status?: string; stats?: Record<string, unknown>; last_error?: string } | null = null;
  let runs: RunRow[] = [];
  if (sb) {
    try {
      const cursor = await sb.from("eth_scan_backfill").select("id,status,stats,last_error").eq("id", "scan-cycle").limit(1);
      const row = !cursor.error && Array.isArray(cursor.data) ? cursor.data[0] : null;
      if (row) cycle = row as NonNullable<typeof cycle>;
      const recent = await sb
        .from("test_scan_runs")
        .select("address,bucket,heat,discovery_source,list_id,dedupe_key,created_at,notes,heat_breakdown")
        .order("created_at", { ascending: false })
        .limit(80);
      if (!recent.error && recent.data) runs = recent.data as RunRow[];
    } catch {
      cycle = null;
      runs = [];
    }
  }
  const stats = (cycle?.stats && typeof cycle.stats === "object" ? cycle.stats : {}) as Record<string, unknown>;
  const lists = loaded.lists.map((list) => {
    const seen = new Set<string>();
    const buckets = { drain: 0, maybe: 0, no: 0 };
    for (const run of runs) {
      if (!runMatchesList(run, list.id)) continue;
      const addr = normalizeAddress(run.address);
      if (!addr || seen.has(addr)) continue;
      seen.add(addr);
      const outcome = classifyOutcome(run);
      if (outcome) buckets[outcome] += 1;
    }
    return {
      id: list.id,
      name: list.name,
      total: list.total,
      scanned: seen.size,
      unscanned: Math.max(0, list.total - seen.size),
      buckets,
    };
  });
  const randomStream = runs
    .filter((run) => run.discovery_source === "random_scan")
    .slice(0, 12)
    .map((run) => ({
      address: run.address || "",
      bucket: run.bucket || "no",
      heat: Number(run.heat || 0),
      at: run.created_at || null,
    }));
  return json({
    ok: true,
    automatic: true,
    manual_start_required: false,
    schedule: "The monitor job runs every 10 minutes and the backfill job every 15. They share one lease. No button starts the loop.",
    phase: String(stats.phase || "scheduled"),
    status: cycle?.status || "scheduled",
    message: String(cycle?.last_error || stats.message || "Waiting for the next scheduled run. Lists are scanned first, then random contracts."),
    current_address: String(stats.current_address || ""),
    random_scanned_this_run: Number(stats.random_scanned || 0),
    random_enabled: loaded.random_scan.enabled,
    lists,
    random_stream: randomStream,
    connected: Boolean(sb),
  });
}
