/**
 * Named master lists for /test. Read-only.
 *
 * List 1 is the funded, credible-but-less-audited curated feed. Order is
 * drain-probability, then tier, then dollars — the same feed the scanner walks.
 *
 * List 2 is the junk-drawer / sketchy-contract list. It loads
 * list2_candidates.json when that file exists, otherwise excluded.csv rows
 * that were dropped under the old sub-$2,000 floor. Either way it applies
 * its own filter: small-dollar band, no big names, no canonical protocols,
 * ranked for abandoned / unaudited / odd-pattern / previously-hacked lineage.
 * Dollars are not the sort key.
 *
 * Bounds are per list in eth-scanner/data/lists.json. Heat rules are untouched.
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";

export {
  LIST1_ID,
  LIST2_ID,
  SCAN_LISTS,
  isScanListId,
  scanList,
  type ScanList,
  type ScanListId,
} from "./scan-lists";

export type OutcomeBucket = "drain" | "maybe" | "no";

export type RandomScanConfig = {
  enabled: boolean;
  gap_ms: number;
  history_cap: number;
  session_cap: number;
};

export type ListContract = {
  address: string;
  protocol: string;
  slug: string;
  est_usd_held: number;
  candidate_reason: string;
  tier: number;
  rank: number;
  drain_probability: number;
  source: string;
  evidence_note: string;
  contract_class: string;
  defillama_eth_tvl: number;
  manual: boolean;
};

export type LoadedList = {
  id: string;
  name: string;
  strategy: string;
  summary: string;
  min_funds_usd: number;
  max_funds_usd: number;
  source: string;
  total: number;
  total_usd: number;
  manual_count: number;
  contracts: ListContract[];
};

type SketchyWeight = { pattern: string; weight: number };
type List2Rules = {
  below_floor_marker: string;
  exclude_reason_markers: string[];
  exclude_name_substrings: string[];
  exclude_exact_names: string[];
  generic_labels: string[];
  sketchy_weights: SketchyWeight[];
};

const ADDRESS_RE = /^0x[0-9a-f]{40}$/;

export function normalizeAddress(raw: unknown): string {
  const text = String(raw ?? "").trim().toLowerCase();
  return ADDRESS_RE.test(text) ? text : "";
}

export function isValidAddress(raw: unknown): boolean {
  return Boolean(normalizeAddress(raw));
}

export function normalizeName(raw: string): string {
  return (raw || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function dataDir(): string {
  return process.env.ETH_SCANNER_DATA_DIR?.trim() || path.join(process.cwd(), "eth-scanner", "data");
}

function listsPath(): string {
  return process.env.ETH_SCANNER_LISTS_JSON?.trim() || path.join(dataDir(), "lists.json");
}

function manualPath(): string {
  return process.env.ETH_SCANNER_LIST_MANUAL?.trim() || path.join(dataDir(), "lists", "manual.json");
}

function readJson(file: string): unknown {
  return JSON.parse(readFileSync(file, "utf8"));
}

function asNumber(value: unknown, fallback = 0): number {
  if (value == null || value === "") return fallback;
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function drainPrior(value: unknown): number {
  let score = asNumber(value, 0);
  if (score > 1) score /= 100;
  if (score < 0) return 0;
  if (score > 1) return 1;
  return score;
}

function list2Rules(doc: Record<string, unknown>): List2Rules {
  const raw = (doc.list2_rules && typeof doc.list2_rules === "object" ? doc.list2_rules : {}) as Record<string, unknown>;
  const weights = Array.isArray(raw.sketchy_weights) ? raw.sketchy_weights : [];
  return {
    below_floor_marker: String(raw.below_floor_marker || "below-2000"),
    exclude_reason_markers: (Array.isArray(raw.exclude_reason_markers) ? raw.exclude_reason_markers : []).map(String),
    exclude_name_substrings: (Array.isArray(raw.exclude_name_substrings) ? raw.exclude_name_substrings : [])
      .map((item) => normalizeName(String(item)))
      .filter(Boolean),
    exclude_exact_names: (Array.isArray(raw.exclude_exact_names) ? raw.exclude_exact_names : [])
      .map((item) => normalizeName(String(item)))
      .filter(Boolean),
    generic_labels: (Array.isArray(raw.generic_labels) ? raw.generic_labels : []).map((item) => normalizeName(String(item))),
    sketchy_weights: weights
      .filter((row): row is SketchyWeight => Boolean(row) && typeof row === "object")
      .map((row) => ({ pattern: String((row as SketchyWeight).pattern || ""), weight: asNumber((row as SketchyWeight).weight) }))
      .filter((row) => row.pattern),
  };
}

export function isBigOrCanonicalName(protocol: string, slug: string, rules: List2Rules): boolean {
  for (const side of [normalizeName(protocol), normalizeName(slug)]) {
    if (!side) continue;
    if (rules.exclude_exact_names.includes(side)) return true;
    if (rules.exclude_name_substrings.some((sub) => sub && side.includes(sub))) return true;
  }
  return false;
}

export function reasonExcluded(reason: string, rules: List2Rules): boolean {
  const low = (reason || "").toLowerCase();
  return rules.exclude_reason_markers.some((marker) => low.includes(marker.toLowerCase()));
}

export function sketchyScore(blob: string, protocol: string, rules: List2Rules): number {
  let score = 0;
  for (const row of rules.sketchy_weights) {
    if (new RegExp(row.pattern, "i").test(blob || "")) score += row.weight;
  }
  const label = normalizeName(protocol);
  score += label && !rules.generic_labels.includes(label) ? 10 : 1;
  return score;
}

function fromRaw(raw: Record<string, unknown>): ListContract | null {
  const address = normalizeAddress(raw.address);
  if (!address) return null;
  const protocol = String(raw.protocol || "");
  const held = raw.est_usd_held == null || raw.est_usd_held === "" ? raw.funds_usd : raw.est_usd_held;
  const tierRaw = asNumber(raw.tier, 99);
  return {
    address,
    protocol,
    slug: String(raw.slug || protocol.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")),
    est_usd_held: asNumber(held, 0),
    candidate_reason: String(raw.candidate_reason || raw.excluded_reason || ""),
    tier: tierRaw >= 1 ? tierRaw : 99,
    rank: asNumber(raw.rank, 1_000_000_000),
    drain_probability: drainPrior(raw.drain_probability),
    source: String(raw.source || ""),
    evidence_note: String(raw.evidence_note || ""),
    contract_class: String(raw.contract_class || raw.category || ""),
    defillama_eth_tvl: asNumber(raw.defillama_eth_tvl, 0),
    manual: false,
  };
}

function rowsOf(payload: unknown): Record<string, unknown>[] {
  const raw = Array.isArray(payload)
    ? payload
    : payload && typeof payload === "object"
      ? ((payload as { candidates?: unknown; rows?: unknown }).candidates
        ?? (payload as { rows?: unknown }).rows
        ?? [])
      : [];
  return Array.isArray(raw) ? raw.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object") : [];
}

function parseCsv(text: string): Record<string, string>[] {
  const lines = text.split(/\r?\n/).filter((line) => line.trim());
  if (!lines.length) return [];
  const headers = splitCsv(lines[0]);
  return lines.slice(1).map((line) => {
    const cols = splitCsv(line);
    const row: Record<string, string> = {};
    headers.forEach((header, index) => {
      row[header] = cols[index] ?? "";
    });
    return row;
  });
}

function splitCsv(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          cur += '"';
          i += 1;
        } else quoted = false;
      } else cur += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

function loadTable(file: string): ListContract[] {
  const text = readFileSync(file, "utf8");
  const records = file.endsWith(".csv") ? parseCsv(text) : rowsOf(readJson(file));
  const out: ListContract[] = [];
  for (const raw of records) {
    const row = fromRaw(raw as Record<string, unknown>);
    if (row) out.push(row);
  }
  return out;
}

function list1Priority(row: ListContract): [number, number, number, number, number, string] {
  return [-row.drain_probability, row.tier, -row.est_usd_held, -row.defillama_eth_tvl, row.rank, row.address];
}

function comparePriority(a: ListContract, b: ListContract): number {
  const left = list1Priority(a);
  const right = list1Priority(b);
  for (let i = 0; i < left.length; i += 1) {
    if (left[i] < right[i]) return -1;
    if (left[i] > right[i]) return 1;
  }
  return 0;
}

function loadList1(dir: string): { contracts: ListContract[]; source: string } {
  const baseFile = path.join(dir, "master_candidates.json");
  const best = new Map<string, ListContract>();
  for (const row of loadTable(baseFile)) {
    const prev = best.get(row.address);
    if (!prev || comparePriority(row, prev) < 0) best.set(row.address, row);
  }
  const handFile = path.join(dir, "hand_ranked_candidates.json");
  try {
    for (const hand of loadTable(handFile)) {
      const prev = best.get(hand.address);
      if (!prev) {
        best.set(hand.address, hand);
        continue;
      }
      best.set(hand.address, {
        ...prev,
        protocol: hand.protocol || prev.protocol,
        slug: hand.slug || prev.slug,
        est_usd_held: hand.est_usd_held || prev.est_usd_held,
        candidate_reason: hand.candidate_reason || prev.candidate_reason,
        tier: hand.tier >= 99 ? prev.tier : hand.tier,
        rank: hand.rank >= 1_000_000_000 ? prev.rank : hand.rank,
        drain_probability: hand.drain_probability,
        source: hand.source || prev.source,
        evidence_note: hand.evidence_note || prev.evidence_note,
        contract_class: hand.contract_class || prev.contract_class,
      });
    }
  } catch {
    /* overlay is optional */
  }
  const contracts = [...best.values()].sort(comparePriority);
  return { contracts, source: "master_candidates" };
}

function findList2File(dir: string): string | null {
  const env = process.env.ETH_SCANNER_LIST2?.trim();
  const candidates = [
    env,
    path.join(dir, "list2_candidates.json"),
    path.join(dir, "list2_candidates.csv"),
    path.join(dir, "lists", "list2_candidates.json"),
    path.join(dir, "lists", "list2_candidates.csv"),
    "/cursor/stores/bot/scanner-list/list2_candidates.json",
    "/cursor/stores/bot/scanner-list/list2_candidates.csv",
  ].filter((item): item is string => Boolean(item));
  for (const file of candidates) {
    try {
      readFileSync(file);
      return file;
    } catch {
      /* try the next location */
    }
  }
  return null;
}

function inBand(usd: number, min: number, max: number): boolean {
  return usd >= min && usd <= max;
}

function selectList2(
  rows: ListContract[],
  min: number,
  max: number,
  rules: List2Rules,
  fromExcluded: boolean,
): ListContract[] {
  const seen = new Set<string>();
  const kept: ListContract[] = [];
  for (const row of rows) {
    if (seen.has(row.address)) continue;
    if (fromExcluded) {
      if (!row.candidate_reason.toLowerCase().includes(rules.below_floor_marker.toLowerCase())) continue;
      if (!inBand(row.est_usd_held, min, max)) continue;
    } else if (row.est_usd_held > 0 && !inBand(row.est_usd_held, min, max)) {
      continue;
    }
    if (reasonExcluded(row.candidate_reason, rules)) continue;
    if (isBigOrCanonicalName(row.protocol, row.slug, rules)) continue;
    seen.add(row.address);
    kept.push(row);
  }
  return kept
    .map((row, index) => ({
      row,
      index,
      score: sketchyScore(
        [row.protocol, row.slug, row.candidate_reason, row.evidence_note, row.contract_class, row.source].filter(Boolean).join(" "),
        row.protocol,
        rules,
      ),
    }))
    .sort((a, b) => b.score - a.score || a.row.protocol.toLowerCase().localeCompare(b.row.protocol.toLowerCase()) || a.row.address.localeCompare(b.row.address) || a.index - b.index)
    .map((item) => item.row);
}

function loadList2(dir: string, min: number, max: number, rules: List2Rules): { contracts: ListContract[]; source: string } {
  const file = findList2File(dir);
  if (file) {
    return { contracts: selectList2(loadTable(file), min, max, rules, false), source: "list2_candidates" };
  }
  const excluded = path.join(dir, "excluded.csv");
  try {
    return { contracts: selectList2(loadTable(excluded), min, max, rules, true), source: "excluded_fallback" };
  } catch {
    return { contracts: [], source: "excluded_fallback" };
  }
}

function readManual(): Record<string, string[]> {
  try {
    const payload = readJson(manualPath());
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return {};
    const out: Record<string, string[]> = {};
    for (const [key, value] of Object.entries(payload)) {
      const seen = new Set<string>();
      const addrs: string[] = [];
      const rows = Array.isArray(value) ? value : [];
      for (const item of rows) {
        const raw = item && typeof item === "object" ? (item as { address?: unknown }).address : item;
        const addr = normalizeAddress(raw);
        if (!addr || seen.has(addr)) continue;
        seen.add(addr);
        addrs.push(addr);
      }
      out[key] = addrs;
    }
    return out;
  } catch {
    return {};
  }
}

export function mergeManualAddresses(list: LoadedList, addresses: string[]): LoadedList {
  const seen = new Set(list.contracts.map((row) => row.address));
  const added = addresses.map(normalizeAddress).filter((addr) => addr && !seen.has(addr));
  if (!added.length) return list;
  const contracts = [...added.map(manualContract), ...list.contracts];
  return {
    ...list,
    contracts,
    total: contracts.length,
    manual_count: list.manual_count + added.length,
  };
}

function manualContract(address: string): ListContract {
  return {
    address,
    protocol: "Manual",
    slug: "manual",
    est_usd_held: 0,
    candidate_reason: "manual-entry",
    tier: 99,
    rank: 1_000_000_000,
    drain_probability: 0,
    source: "manual",
    evidence_note: "Added on the list config or from the /test form.",
    contract_class: "manual",
    defillama_eth_tvl: 0,
    manual: true,
  };
}

export function loadRandomScanConfig(doc?: Record<string, unknown>): RandomScanConfig {
  const source = doc ?? (readJson(listsPath()) as Record<string, unknown>);
  const raw = (source.random_scan && typeof source.random_scan === "object" ? source.random_scan : {}) as Record<string, unknown>;
  return {
    enabled: raw.enabled !== false,
    gap_ms: Math.round(asNumber(raw.gap_ms, 8000)),
    history_cap: Math.max(1, Math.round(asNumber(raw.history_cap, 20))),
    session_cap: Math.max(1, Math.round(asNumber(raw.session_cap, 40))),
  };
}

export function loadMasterLists(): { random_scan: RandomScanConfig; lists: LoadedList[] } {
  const doc = readJson(listsPath()) as Record<string, unknown>;
  const rules = list2Rules(doc);
  const dir = dataDir();
  const manual = readManual();
  const specs = Array.isArray(doc.lists) ? doc.lists : [];
  const lists: LoadedList[] = [];
  for (const raw of specs) {
    if (!raw || typeof raw !== "object") continue;
    const spec = raw as Record<string, unknown>;
    const id = String(spec.id || "").trim();
    if (!id) continue;
    const min = asNumber(spec.min_funds_usd, 0);
    const max = asNumber(spec.max_funds_usd, 0);
    const loaded = id === "list-2" ? loadList2(dir, min, max, rules) : loadList1(dir);
    const seen = new Set(loaded.contracts.map((row) => row.address));
    const added = (manual[id] || []).filter((addr) => !seen.has(addr)).map(manualContract);
    const contracts = [...added, ...loaded.contracts];
    lists.push({
      id,
      name: String(spec.name || id),
      strategy: String(spec.strategy || ""),
      summary: String(spec.summary || ""),
      min_funds_usd: min,
      max_funds_usd: max,
      source: loaded.source,
      total: contracts.length,
      total_usd: Math.round(contracts.reduce((sum, row) => sum + row.est_usd_held, 0) * 100) / 100,
      manual_count: added.length,
      contracts,
    });
  }
  return { random_scan: loadRandomScanConfig(doc), lists };
}

export function appendManualAddress(listId: string, address: string): { ok: true; address: string } | { ok: false; error: string } {
  const addr = normalizeAddress(address);
  if (!addr) return { ok: false, error: "Enter a 0x address with 40 hex characters." };
  const { lists } = loadMasterLists();
  const list = lists.find((item) => item.id === listId);
  if (!list) return { ok: false, error: "Unknown list." };
  if (list.contracts.some((row) => row.address === addr)) {
    return { ok: false, error: `That address is already on ${list.name}.` };
  }
  const file = manualPath();
  mkdirSync(path.dirname(file), { recursive: true });
  const current = readManual();
  const rows = [...(current[listId] || []), addr];
  let existing: Record<string, unknown> = {};
  try {
    const payload = readJson(file);
    if (payload && typeof payload === "object" && !Array.isArray(payload)) existing = payload as Record<string, unknown>;
  } catch {
    existing = {};
  }
  existing[listId] = rows;
  for (const [key, value] of Object.entries(current)) {
    if (!(key in existing)) existing[key] = value;
  }
  writeFileSync(file, `${JSON.stringify(existing, null, 2)}\n`, "utf8");
  return { ok: true, address: addr };
}

export function writeRandomScanConfig(next: Partial<RandomScanConfig>): RandomScanConfig {
  const file = listsPath();
  const doc = readJson(file) as Record<string, unknown>;
  const prev = loadRandomScanConfig(doc);
  const merged: RandomScanConfig = {
    enabled: typeof next.enabled === "boolean" ? next.enabled : prev.enabled,
    gap_ms: Number.isFinite(Number(next.gap_ms)) ? Math.round(Number(next.gap_ms)) : prev.gap_ms,
    history_cap: Number.isFinite(Number(next.history_cap)) ? Math.max(1, Math.round(Number(next.history_cap))) : prev.history_cap,
    session_cap: Number.isFinite(Number(next.session_cap)) ? Math.max(1, Math.round(Number(next.session_cap))) : prev.session_cap,
  };
  doc.random_scan = merged;
  writeFileSync(file, `${JSON.stringify(doc, null, 2)}\n`, "utf8");
  return merged;
}

type ScanLike = {
  heat?: unknown;
  heat_breakdown?: unknown;
  notes?: unknown;
  drop_reason?: unknown;
};

export function callerProfitDelta(run: ScanLike): number {
  const blobs = [
    JSON.stringify(run.heat_breakdown ?? {}),
    JSON.stringify(run.notes ?? []),
    String(run.drop_reason ?? ""),
  ];
  let max = 0;
  for (const blob of blobs) {
    for (const match of blob.matchAll(/caller_profit_delta[=:](\d+)/g)) {
      const n = Number(match[1]);
      if (n > max) max = n;
    }
  }
  if (run.heat_breakdown && typeof run.heat_breakdown === "object" && "caller_profit_delta" in run.heat_breakdown) {
    const n = Number((run.heat_breakdown as { caller_profit_delta?: unknown }).caller_profit_delta);
    if (Number.isFinite(n) && n > max) max = n;
  }
  return max;
}

/** Drain found / Maybe / No. Null means the address has no scan row. */
export function classifyOutcome(run: ScanLike | null | undefined): OutcomeBucket | null {
  if (!run) return null;
  const heat = Number(run.heat ?? 0);
  const breakdown = run.heat_breakdown;
  const fundsInHeat = breakdown && typeof breakdown === "object"
    ? Number((breakdown as { funds_in_heat?: unknown }).funds_in_heat ?? 0)
    : 0;
  if ((Number.isFinite(fundsInHeat) && fundsInHeat > 0) || callerProfitDelta(run) > 0) return "drain";
  if (Number.isFinite(heat) && heat > 0) return "maybe";
  return "no";
}

export function runMatchesList(
  run: { list_id?: unknown; discovery_source?: unknown; dedupe_key?: unknown },
  listId: string,
): boolean {
  const id = String(run.list_id || "").trim();
  if (id) return id === listId;
  const dedupe = String(run.dedupe_key || "");
  const tagged = /^master-list:([^:]+):(0x[0-9a-f]{40})$/.exec(dedupe);
  if (tagged && tagged[1] !== "0x" && !tagged[1].startsWith("0x")) return tagged[1] === listId;
  if (/^master-list:0x[0-9a-f]{40}$/.test(dedupe)) return listId === "list-1";
  return listId === "list-1" && String(run.discovery_source || "") === "master_list";
}
