/**
 * Named master lists for /test. Read-only ranking and display.
 * Adding an address appends it to the per-list manual file (and Supabase
 * when that table exists). No scan, no exploit payload.
 */

import { NextResponse } from "next/server";
import {
  appendManualAddress,
  classifyOutcome,
  isValidAddress,
  loadMasterLists,
  mergeManualAddresses,
  normalizeAddress,
  runMatchesList,
  writeRandomScanConfig,
  type LoadedList,
  type OutcomeBucket,
  type RandomScanConfig,
} from "@/lib/eth-scanner/lists";
import { createServiceSupabaseClient } from "@/lib/eth-scanner/service-supabase";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function json(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" },
  });
}

type ScanRow = {
  address?: unknown;
  heat?: unknown;
  heat_breakdown?: unknown;
  notes?: unknown;
  list_id?: unknown;
  dedupe_key?: unknown;
  discovery_source?: unknown;
  created_at?: unknown;
  funds_usd?: unknown;
  status?: unknown;
  drop_reason?: unknown;
};

async function loadScanRows(): Promise<ScanRow[]> {
  const sb = createServiceSupabaseClient();
  if (!sb) return [];
  const withList = "address,heat,heat_breakdown,notes,list_id,dedupe_key,discovery_source,created_at,funds_usd,status,drop_reason";
  const without = "address,heat,heat_breakdown,notes,dedupe_key,discovery_source,created_at,funds_usd,status,drop_reason";
  let columns = withList;
  const rows: ScanRow[] = [];
  let from = 0;
  while (from < 20_000) {
    const { data, error } = await sb
      .from("test_scan_runs")
      .select(columns)
      .order("created_at", { ascending: false })
      .range(from, from + 999);
    if (error) {
      if (columns === withList && /list_id|schema cache|column/i.test(error.message || "")) {
        columns = without;
        continue;
      }
      break;
    }
    const page = (data ?? []) as ScanRow[];
    rows.push(...page);
    if (page.length < 1000) break;
    from += 1000;
  }
  return rows;
}

function slimContract(
  row: LoadedList["contracts"][number],
  scan: ScanRow | undefined,
) {
  const outcome = classifyOutcome(scan ?? null);
  return {
    address: row.address,
    protocol: row.protocol,
    est_usd_held: row.est_usd_held,
    candidate_reason: row.candidate_reason,
    tier: row.tier,
    source: row.source,
    manual: row.manual,
    evidence_note: row.evidence_note.slice(0, 180),
    scanned: Boolean(scan),
    outcome,
    heat: scan ? Number(scan.heat ?? 0) : null,
    funds_usd: scan?.funds_usd ?? null,
    status: scan?.status ?? null,
  };
}

function presentList(list: LoadedList, runs: ScanRow[], detailed: boolean) {
  const latest = new Map<string, ScanRow>();
  for (const run of runs) {
    if (!runMatchesList(run, list.id)) continue;
    const addr = normalizeAddress(run.address);
    if (!addr || latest.has(addr)) continue;
    latest.set(addr, run);
  }
  const contracts = list.contracts.map((row) => slimContract(row, latest.get(row.address)));
  const buckets: Record<OutcomeBucket, number> = { drain: 0, maybe: 0, no: 0 };
  let scanned = 0;
  for (const row of contracts) {
    if (!row.scanned || !row.outcome) continue;
    scanned += 1;
    buckets[row.outcome] += 1;
  }
  return {
    id: list.id,
    name: list.name,
    strategy: list.strategy,
    summary: list.summary,
    min_funds_usd: list.min_funds_usd,
    max_funds_usd: list.max_funds_usd,
    source: list.source,
    total: list.total,
    total_usd: list.total_usd,
    manual_count: list.manual_count,
    scanned,
    unscanned: list.total - scanned,
    buckets,
    contracts: detailed ? contracts : undefined,
  };
}

async function remoteManual(): Promise<Record<string, string[]>> {
  const sb = createServiceSupabaseClient();
  if (!sb) return {};
  const { data, error } = await sb.from("scanner_list_addresses").select("list_id,address");
  if (error || !data) return {};
  const out: Record<string, string[]> = {};
  for (const row of data as { list_id?: string; address?: string }[]) {
    const id = String(row.list_id || "");
    const addr = normalizeAddress(row.address);
    if (!id || !addr) continue;
    out[id] = [...(out[id] || []), addr];
  }
  return out;
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const summary = url.searchParams.get("summary") === "1";
  const wanted = (url.searchParams.get("list") || "").trim();
  try {
    const loaded = loadMasterLists();
    const extra = summary ? {} : await remoteManual();
    const named = loaded.lists.map((list) => mergeManualAddresses(list, extra[list.id] || []));
    const focus = wanted || named[0]?.id || "";
    const runs = summary ? [] : await loadScanRows();
    const lists = named.map((list) => presentList(list, runs, !summary && list.id === focus));
    const selected = lists.find((list) => list.id === focus) ?? null;
    const overview = lists.map((list) => {
      const { contracts: _omit, ...rest } = list;
      void _omit;
      return rest;
    });
    return json({
      ok: true,
      random_scan: loaded.random_scan,
      lists: summary ? overview : overview,
      selected: summary ? null : selected,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "list load failed";
    return json({ ok: false, error: message }, 500);
  }
}

export async function POST(req: Request) {
  let body: unknown = {};
  try {
    const text = await req.text();
    body = text ? JSON.parse(text) : {};
  } catch {
    return json({ ok: false, error: "invalid json" }, 400);
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return json({ ok: false, error: "expected a JSON object" }, 400);
  }
  const record = body as { list_id?: unknown; address?: unknown; random_scan?: unknown };

  if (record.random_scan && typeof record.random_scan === "object") {
    try {
      const saved = writeRandomScanConfig(record.random_scan as Partial<RandomScanConfig>);
      return json({ ok: true, persisted: "file", random_scan: saved });
    } catch (err) {
      const message = err instanceof Error ? err.message : "could not write random scan config";
      return json({ ok: false, error: message, persisted: false }, 500);
    }
  }

  const listId = String(record.list_id || "").trim();
  const address = normalizeAddress(record.address);
  if (!listId) return json({ ok: false, error: "list_id is required" }, 400);
  if (!address || !isValidAddress(address)) {
    return json({ ok: false, error: "Enter a 0x address with 40 hex characters." }, 400);
  }
  const loaded = loadMasterLists();
  const list = loaded.lists.find((item) => item.id === listId);
  if (!list) return json({ ok: false, error: "Unknown list." }, 400);
  if (list.contracts.some((row) => row.address === address)) {
    return json({ ok: false, error: `That address is already on ${list.name}.` }, 409);
  }

  let fileSaved = false;
  try {
    const added = appendManualAddress(listId, address);
    fileSaved = added.ok;
    if (!added.ok && /already/.test(added.error)) {
      return json({ ok: false, error: added.error }, 409);
    }
  } catch {
    fileSaved = false;
  }

  const sb = createServiceSupabaseClient();
  let remote: "saved" | "skipped" | "unavailable" = "unavailable";
  if (sb) {
    const { error } = await sb.from("scanner_list_addresses").upsert(
      { list_id: listId, address },
      { onConflict: "list_id,address" },
    );
    remote = error ? "skipped" : "saved";
  }
  if (!fileSaved && remote !== "saved") {
    return json({
      ok: false,
      error: "Could not store that address. Edit eth-scanner/data/lists/manual.json, or apply the scanner_list_addresses migration.",
    }, 500);
  }
  return json({ ok: true, list_id: listId, address, persisted: fileSaved ? "file" : "supabase", remote });
}
