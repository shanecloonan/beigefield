/**
 * Aggregate Blend desk stats and the heat leaderboard.
 * One finished scan per address. Heat is the rank. Buckets stay the desk's.
 */

import { classifyOutcome, normalizeAddress } from "@/lib/eth-scanner/lists";
import { DEFAULT_CHAIN, normalizeChain } from "@/lib/eth-scanner/chain-filters";

export { CHAIN_FILTERS, DEFAULT_CHAIN, normalizeChain } from "@/lib/eth-scanner/chain-filters";

export const LEADERBOARD_LIMIT = 100;
/** A high-heat contract is stale when its latest scan is older than this. */
export const STALE_AFTER_MS = 14 * 24 * 60 * 60 * 1000;
export const STALE_MIN_HEAT = 1;

export type BlendVerdict = "yes" | "maybe" | "no" | "other";

export type BlendRunLike = {
  address?: unknown;
  heat?: unknown;
  blend_heat?: unknown;
  blend_bucket?: unknown;
  bucket?: unknown;
  funds_usd?: unknown;
  tvl_usd?: unknown;
  money_at_risk_usd?: unknown;
  contract_name?: unknown;
  created_at?: unknown;
  status?: unknown;
  heat_breakdown?: unknown;
  notes?: unknown;
  drop_reason?: unknown;
  chain?: unknown;
};

export type Liveness = "live" | "dead" | "already-exploited";

export type LeaderRow = {
  address: string;
  chain: string;
  heat: number;
  bucket: string;
  verdict: BlendVerdict;
  label: string;
  funds_usd: number | null;
  contract_name: string | null;
  scanned_at: string | null;
  liveness: Liveness;
  peak_heat: number;
  /** The peak before a rescore withdrew a false stamp. Null when no rescore rewrote it. */
  original_peak: number | null;
  history_count: number;
  stale: boolean;
  score_state: "" | "provisional" | "final";
  pending_stages: string[];
  /** Display labels from the heat breakdown. Empty when the scan stored none. */
  evidence_tags: string[];
};

export type BlendBoard = {
  chain: string;
  scanned: number;
  totals: Record<BlendVerdict, number>;
  leaderboard: LeaderRow[];
  flagged: LeaderRow[];
  requeue: LeaderRow[];
};

const FINISHED = new Set(["", "done", "dropped", "gated"]);
const VERDICT_LABEL: Record<Exclude<BlendVerdict, "other">, string> = {
  yes: "Yes",
  maybe: "Maybe",
  no: "No",
};

function numberOrNull(value: unknown): number | null {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** A row with no chain is an Ethereum row. That keeps today's totals stable. */
export function chainOf(row: BlendRunLike): string {
  return normalizeChain(row.chain);
}

export function heatOf(row: BlendRunLike): number {
  const values = [numberOrNull(row.blend_heat), numberOrNull(row.heat)].filter(
    (n): n is number => n != null,
  );
  if (!values.length) return 0;
  return Math.max(...values);
}

export function fundsOf(row: BlendRunLike): number | null {
  for (const value of [row.funds_usd, row.money_at_risk_usd, row.tvl_usd]) {
    const n = numberOrNull(value);
    if (n != null) return n;
  }
  return null;
}

/** Desk bucket, in the page's words. Blend's drain-found is Yes. */
export function verdictOf(row: BlendRunLike): { bucket: string; verdict: BlendVerdict; label: string } {
  const raw = String(row.blend_bucket || "").trim().toLowerCase();
  if (raw === "drain-found" || raw === "drain" || raw === "yes") {
    return { bucket: "drain-found", verdict: "yes", label: VERDICT_LABEL.yes };
  }
  if (raw === "maybe") return { bucket: "maybe", verdict: "maybe", label: VERDICT_LABEL.maybe };
  if (raw === "no") return { bucket: "no", verdict: "no", label: VERDICT_LABEL.no };
  const outcome = classifyOutcome({
    heat: heatOf(row),
    heat_breakdown: row.heat_breakdown,
    notes: row.notes,
    drop_reason: row.drop_reason,
  });
  if (outcome === "drain") return { bucket: "drain-found", verdict: "yes", label: VERDICT_LABEL.yes };
  if (outcome === "maybe") return { bucket: "maybe", verdict: "maybe", label: VERDICT_LABEL.maybe };
  if (outcome === "no") return { bucket: "no", verdict: "no", label: VERDICT_LABEL.no };
  const bucket = raw || String(row.bucket || "").trim() || "other";
  return { bucket, verdict: "other", label: bucket };
}

function finished(row: BlendRunLike): boolean {
  return FINISHED.has(String(row.status || "").trim().toLowerCase());
}

function breakdownOf(row: BlendRunLike): Record<string, unknown> | null {
  const raw = row.heat_breakdown;
  if (!raw) return null;
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw) as unknown;
      return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : null;
    } catch {
      return null;
    }
  }
  return typeof raw === "object" ? (raw as Record<string, unknown>) : null;
}

/** Trace evidence that the contract already paid an EOA and then collapsed. */
export function livenessOf(row: BlendRunLike): Liveness {
  const block = breakdownOf(row)?.liveness;
  const status =
    block && typeof block === "object" ? String((block as { status?: unknown }).status || "") : "";
  if (status === "dead" || status === "already-exploited") return status;
  return "live";
}

function scoreOf(row: BlendRunLike): { state: "" | "provisional" | "final"; pending: string[] } {
  const raw = row.heat_breakdown;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return { state: "", pending: [] };
  const record = raw as { score_state?: unknown; pending_stages?: unknown };
  const state = record.score_state === "provisional" || record.score_state === "final" ? record.score_state : "";
  const pending = Array.isArray(record.pending_stages)
    ? record.pending_stages.map((name) => String(name || "")).filter(Boolean)
    : [];
  return { state, pending };
}

/** Labels the board can show. Points stay in the breakdown; this list is display only. */
export function evidenceTags(breakdown: Record<string, unknown> | null): string[] {
  if (!breakdown) return [];
  const amount = (key: string) => {
    const value = Number(breakdown[key]);
    return Number.isFinite(value) ? value : 0;
  };
  const flagged = (key: string) => breakdown[key] === true || amount(key) > 0;
  const tags: string[] = [];
  if (amount("invariants_failed") > 0) tags.push("invariant");
  if (flagged("sequence")) tags.push("sequence");
  if (flagged("oracle")) tags.push("oracle");
  if (amount("static_evidence") > 0) tags.push("static");
  if (amount("corpus_evidence") > 0) tags.push("corpus");
  if (amount("clone_evidence") > 0) tags.push("clone");
  if (amount("surface_evidence") > 0 || flagged("bytecode_surface")) tags.push("surface");
  if (flagged("storage_layout")) tags.push("layout");
  if (flagged("source_metadata")) tags.push("metadata");
  if (flagged("erc4626_suite")) tags.push("erc4626");
  if (flagged("crytic_properties")) tags.push("properties");
  if (flagged("weird_tokens")) tags.push("weird");
  if (flagged("decompile_triage")) tags.push("decompile");
  if (amount("certora_evidence") > 0 || flagged("certora")) tags.push("certora");
  if (flagged("hevm")) tags.push("hevm");
  if (flagged("wake")) tags.push("wake");
  if (flagged("pyrometer")) tags.push("pyrometer");
  if (amount("smt_evidence") > 0 || flagged("smt")) tags.push("smt");
  if (amount("upgrade_evidence") > 0 || flagged("upgrade")) tags.push("upgrade");
  if (amount("unprotected_evidence") > 0) tags.push("unprotected");
  if (amount("proxy_evidence") > 0) tags.push("proxy");
  if (amount("fresh_evidence") > 0) tags.push("fresh");
  if (amount("eoa_admin") > 0) tags.push("admin");
  return tags;
}

function toRow(address: string, row: BlendRunLike): LeaderRow {
  const decision = verdictOf(row);
  const name = String(row.contract_name || "").trim();
  const score = scoreOf(row);
  return {
    address,
    chain: chainOf(row),
    heat: heatOf(row),
    bucket: decision.bucket,
    verdict: decision.verdict,
    label: decision.label,
    funds_usd: fundsOf(row),
    contract_name: name || null,
    scanned_at: row.created_at ? String(row.created_at) : null,
    liveness: livenessOf(row),
    peak_heat: heatOf(row),
    history_count: 1,
    stale: false,
    score_state: score.state,
    pending_stages: score.pending,
    original_peak: null,
    evidence_tags: evidenceTags(breakdownOf(row)),
  };
}

function auditPeak(row: BlendRunLike): number | null {
  const breakdown = breakdownOf(row);
  if (!breakdown) return null;
  return numberOrNull(breakdown.original_peak);
}

/** A rescore stores the recomputed all-time peak. Raw heat on that row is not a second peak. */
function contributedHeat(row: BlendRunLike): number {
  const breakdown = breakdownOf(row);
  if (breakdown && breakdown.rescore === "evidence-read") {
    const recomputed = numberOrNull(breakdown.peak_heat);
    if (recomputed != null) return recomputed;
  }
  return heatOf(row);
}

function scannedAt(row: LeaderRow): number {
  const parsed = Date.parse(row.scanned_at || "");
  return Number.isFinite(parsed) ? parsed : 0;
}

/** The newest finished scan wins. Heat is that scan's heat, not the historical max. */
function newer(next: LeaderRow, prev: LeaderRow): boolean {
  const nextAt = scannedAt(next);
  const prevAt = scannedAt(prev);
  if (nextAt !== prevAt) return nextAt > prevAt;
  return next.heat > prev.heat;
}

function observationKey(chain: string, address: string, row: BlendRunLike): string {
  return [
    chain,
    address,
    String(row.created_at || ""),
    String(row.heat ?? ""),
    String(row.blend_heat ?? ""),
    String(row.status || ""),
    String(row.blend_bucket || ""),
    String(row.bucket || ""),
  ].join("|");
}

/** Unique finished contracts, ranked by all-time heat. Age does not remove a row. */
export function summarizeBlendRuns(
  rows: BlendRunLike[],
  limit = LEADERBOARD_LIMIT,
  now = Date.now(),
  chain = DEFAULT_CHAIN,
): BlendBoard {
  const selected = normalizeChain(chain);
  const best = new Map<string, { latest: LeaderRow; peak: number; count: number; original: number | null }>();
  const seen = new Set<string>();
  for (const row of rows) {
    if (!finished(row)) continue;
    const rowChain = chainOf(row);
    if (selected !== "all" && rowChain !== selected) continue;
    const address = rowChain === "ethereum" ? normalizeAddress(row.address) : String(row.address || "").trim();
    if (!address) continue;
    const mark = observationKey(rowChain, address, row);
    if (seen.has(mark)) continue;
    seen.add(mark);
    const next = toRow(address, row);
    next.chain = rowChain;
    const key = `${rowChain}:${address}`;
    const prev = best.get(key);
    const contributed = contributedHeat(row);
    const audit = auditPeak(row);
    if (!prev) {
      best.set(key, { latest: next, peak: contributed, count: 1, original: audit });
      continue;
    }
    prev.peak = Math.max(prev.peak, contributed);
    if (audit != null) prev.original = prev.original == null ? audit : Math.max(prev.original, audit);
    prev.count += 1;
    if (newer(next, prev.latest)) prev.latest = next;
  }
  const ranked = [...best.values()].map((acc) => {
    const age = acc.latest.scanned_at ? now - scannedAt(acc.latest) : Number.POSITIVE_INFINITY;
    const stale =
      acc.latest.liveness === "live" && acc.peak >= STALE_MIN_HEAT && age >= STALE_AFTER_MS;
    return { ...acc.latest, peak_heat: acc.peak, original_peak: acc.original, history_count: acc.count, stale };
  });
  ranked.sort((a, b) => {
    if (b.peak_heat !== a.peak_heat) return b.peak_heat - a.peak_heat;
    const funds = (b.funds_usd ?? -1) - (a.funds_usd ?? -1);
    if (funds !== 0) return funds;
    return a.address.localeCompare(b.address);
  });
  const totals: Record<BlendVerdict, number> = { yes: 0, maybe: 0, no: 0, other: 0 };
  for (const row of ranked) totals[row.verdict] += 1;
  const cap = Number.isFinite(limit) && limit > 0 ? Math.floor(limit) : LEADERBOARD_LIMIT;
  const flagged = ranked.filter((row) => row.liveness !== "live");
  const requeue = ranked.filter((row) => row.stale);
  return {
    chain: selected,
    scanned: ranked.length,
    totals,
    leaderboard: ranked.slice(0, cap),
    flagged: flagged.slice(0, cap),
    requeue,
  };
}
