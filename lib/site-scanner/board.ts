/** All-time website heat. Age does not drop a host. */

export type SiteHit = {
  host?: unknown;
  url?: unknown;
  heat?: unknown;
  peak_heat?: unknown;
  score_state?: unknown;
  pending_stages?: unknown;
  findings?: unknown;
  mode?: unknown;
  updated_at?: unknown;
  created_at?: unknown;
};

export type SiteRow = {
  host: string;
  url: string;
  heat: number;
  peak_heat: number;
  score_state: string;
  pending_stages: string[];
  findings: { id?: string; title?: string; heat?: number; evidence?: string; remediation?: string; stage?: string }[];
  mode: string;
  scanned_at: string | null;
};

function num(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

export function summarizeSiteHits(rows: SiteHit[], limit = 100): SiteRow[] {
  const best = new Map<string, SiteRow>();
  for (const row of rows) {
    const host = String(row.host || "").trim().toLowerCase();
    if (!host) continue;
    const heat = num(row.heat);
    const peak = Math.max(heat, num(row.peak_heat));
    const pending = Array.isArray(row.pending_stages) ? row.pending_stages.map((item) => String(item)) : [];
    const findings = Array.isArray(row.findings) ? row.findings as SiteRow["findings"] : [];
    const next: SiteRow = {
      host,
      url: String(row.url || `https://${host}/`),
      heat,
      peak_heat: peak,
      score_state: String(row.score_state || ""),
      pending_stages: pending,
      findings,
      mode: String(row.mode || "passive"),
      scanned_at: row.updated_at ? String(row.updated_at) : row.created_at ? String(row.created_at) : null,
    };
    const prev = best.get(host);
    if (!prev) {
      best.set(host, next);
      continue;
    }
    const newer = !prev.scanned_at || (next.scanned_at != null && next.scanned_at >= prev.scanned_at);
    const chosen = newer ? next : prev;
    chosen.peak_heat = Math.max(prev.peak_heat, next.peak_heat);
    best.set(host, chosen);
  }
  return [...best.values()]
    .sort((a, b) => b.peak_heat - a.peak_heat || b.heat - a.heat || a.host.localeCompare(b.host))
    .slice(0, limit);
}
