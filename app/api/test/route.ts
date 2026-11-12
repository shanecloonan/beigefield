/**
 * Read-only ETH scanner triage feed for /test.
 * Uses the service-role key server-side only. Never a scanner runtime.
 * When the key is unset, surfaces the local dry-run store if present.
 */

import { NextResponse } from "next/server";
import { capabilityNote, fixtureCatalog, pythonCapability, researchFixtureCatalog, scannerCapabilities } from "@/lib/eth-scanner/capabilities";
import { listResearchReceipts, loadDryRunStore } from "@/lib/eth-scanner/local-store";
import { loadTestScanHistory } from "@/lib/eth-scanner/persist-test-results";
import { BUCKETS } from "@/lib/eth-scanner/receipt";
import { createServiceSupabaseClient } from "@/lib/eth-scanner/service-supabase";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";


function serviceClient() {
  return createServiceSupabaseClient();
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const bucket = url.searchParams.get("bucket");
  const limit = Math.min(200, Math.max(1, Number(url.searchParams.get("limit") || 80)));
  const sb = serviceClient();
  const caps = scannerCapabilities();
  const fixtures = fixtureCatalog();
  const modeNote = capabilityNote(caps);
  const python_runtime = pythonCapability();

  if (!sb) {
    const local = loadDryRunStore();
    const targets = local?.targets ?? [];
    const results = local?.results ?? [];
    const counts: Record<string, number> = Object.fromEntries(BUCKETS.map((b) => [b, 0]));
    for (const t of targets) {
      const b = typeof t.bucket === "string" ? t.bucket : "";
      if (b && counts[b] != null) counts[b] += 1;
    }
    const filtered = bucket && (BUCKETS as readonly string[]).includes(bucket)
      ? targets.filter((t) => t.bucket === bucket)
      : targets;
    return NextResponse.json({
      ok: true,
      ...caps,
      dry_run: true,
      // Vercel instances don't share /tmp: the table can't be trusted to
      // survive between requests, so the client keeps a session queue.
      ephemeral_store: Boolean(process.env.VERCEL),
      buckets: BUCKETS,
      counts,
      targets: filtered.slice(0, limit),
      results: results.slice(0, limit),
      history: { runs: [], findings: [] },
      fixtures,
      research_fixtures: researchFixtureCatalog(),
      research_receipts: listResearchReceipts(12),
      python_runtime,
      note: local
        ? `${modeNote} Showing eth-scanner/work/dry-run-store.json. Download receipt is Markdown from work/receipts/ when present.`
        : `${modeNote} Queue is empty until you click Run (or use the CLI).`,
    });
  }

  const history = await loadTestScanHistory({ limit: Math.min(40, limit) }, sb);

  let targetsQuery = sb
    .from("eth_scan_targets")
    .select("address,bytecode_hash,tvl_usd,status,src_confidence,ir_confidence,heat,bucket,funds_usd,funds_breakdown,funds_status,funds_checked_at,updated_at")
    .order("updated_at", { ascending: false })
    .limit(limit);
  if (bucket && (BUCKETS as readonly string[]).includes(bucket)) {
    targetsQuery = targetsQuery.eq("bucket", bucket);
  }

  const [targetsRes, resultsRes] = await Promise.all([
    targetsQuery,
    sb
      .from("eth_scan_results")
      .select("id,address,bucket,heat,stage_trace,notes,funds_usd,funds_breakdown,funds_status,funds_checked_at,created_at")
      .order("created_at", { ascending: false })
      .limit(limit),
  ]);

  if (targetsRes.error || resultsRes.error) {
    const err = targetsRes.error?.message || resultsRes.error?.message || "query failed";
    const missing = /does not exist|schema cache|relation/i.test(err);
    return NextResponse.json({
      ok: true,
      ...caps,
      dry_run: missing || caps.dry_run,
      buckets: BUCKETS,
      counts: Object.fromEntries(BUCKETS.map((b) => [b, 0])),
      targets: [],
      results: [],
      history: { runs: history.runs, findings: history.findings, error: history.error },
      fixtures,
      research_fixtures: researchFixtureCatalog(),
      research_receipts: listResearchReceipts(12),
      python_runtime,
      note: missing
        ? "eth_scan_* tables missing — apply eth-scanner/supabase/migrations/20261027_eth_scanner_queue.sql. Detailed /test rows use supabase/migrations/*_test_results.sql. Run still writes the local dry-run store."
        : err,
    });
  }

  const targets = targetsRes.data ?? [];
  const counts: Record<string, number> = Object.fromEntries(BUCKETS.map((b) => [b, 0]));
  for (const t of targets) {
    if (t.bucket && counts[t.bucket] != null) counts[t.bucket] += 1;
  }

  return NextResponse.json({
    ok: true,
    ...caps,
    dry_run: false,
    ephemeral_store: false,
    buckets: BUCKETS,
    counts,
    targets,
    results: resultsRes.data ?? [],
    history: { runs: history.runs, findings: history.findings, error: history.error },
    fixtures,
    research_fixtures: researchFixtureCatalog(),
    research_receipts: listResearchReceipts(12),
    python_runtime,
    note: `${modeNote} Automation never stamps yes. Low IR stays in manual-review. Detailed /test history loads from test_scan_*.`,
  });
}
