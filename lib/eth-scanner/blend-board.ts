/**
 * Aggregate Blend desk stats and the heat leaderboard.
 * One finished scan per address. Heat is the rank. Buckets stay the desk's.
 */

import { classifyOutcome, normalizeAddress } from "@/lib/eth-scanner/lists";

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
};

export type Liveness = "live" | "dead" | "already-exploited";

export type LeaderRow = {
  address: string;
  heat: number;
  bucket: string;
  verdict: BlendVerdict;
  label: string;
  funds_usd: number | null;
  contract_name: string | null;
  scanned_at: string | null;
  liveness: Liveness;
  peak_heat: number;
  history_count: number;
  stale: boolean;
};

export type BlendBoard = {
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

function toRow(address: string, row: BlendRunLike): LeaderRow {
  const decision = verdictOf(row);
  const name = String(row.contract_name || "").trim();
  return {
    address,
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
  };
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

/** Unique finished contracts, ranked by the latest heat. Drained rows stay off the hot list. */
export function summarizeBlendRuns(
  rows: BlendRunLike[],
  limit = LEADERBOARD_LIMIT,
  now = Date.now(),
): BlendBoard {
  const best = new Map<string, { latest: LeaderRow; peak: number; count: number }>();
  for (const row of rows) {
    if (!finished(row)) continue;
    const address = normalizeAddress(row.address);
    if (!address) continue;
    const next = toRow(address, row);
    const prev = best.get(address);
    if (!prev) {
      best.set(address, { latest: next, peak: next.heat, count: 1 });
      continue;
    }
    prev.peak = Math.max(prev.peak, next.heat);
    prev.count += 1;
    if (newer(next, prev.latest)) prev.latest = next;
  }
  const ranked = [...best.values()].map((acc) => {
    const age = acc.latest.scanned_at ? now - scannedAt(acc.latest) : Number.POSITIVE_INFINITY;
    const stale =
      acc.latest.liveness === "live" && acc.peak >= STALE_MIN_HEAT && age >= STALE_AFTER_MS;
    return { ...acc.latest, peak_heat: acc.peak, history_count: acc.count, stale };
  });
  ranked.sort((a, b) => {
    if (b.heat !== a.heat) return b.heat - a.heat;
    const funds = (b.funds_usd ?? -1) - (a.funds_usd ?? -1);
    if (funds !== 0) return funds;
    return a.address.localeCompare(b.address);
  });
  const totals: Record<BlendVerdict, number> = { yes: 0, maybe: 0, no: 0, other: 0 };
  for (const row of ranked) totals[row.verdict] += 1;
  const cap = Number.isFinite(limit) && limit > 0 ? Math.floor(limit) : LEADERBOARD_LIMIT;
  const hot = ranked.filter((row) => row.liveness === "live");
  const flagged = ranked.filter((row) => row.liveness !== "live");
  const requeue = ranked.filter((row) => row.stale);
  return {
    scanned: ranked.length,
    totals,
    leaderboard: hot.slice(0, cap),
    flagged: flagged.slice(0, cap),
    requeue,
  };
}
