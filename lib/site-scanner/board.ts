/** All-time website heat. Age does not drop a host. */

export type SiteTech = {
  name: string;
  version: string;
  source: string;
  eol: boolean;
};

export type SiteHit = {
  host?: unknown;
  url?: unknown;
  heat?: unknown;
  peak_heat?: unknown;
  score_state?: unknown;
  pending_stages?: unknown;
  findings?: unknown;
  heat_breakdown?: unknown;
  mode?: unknown;
  updated_at?: unknown;
  created_at?: unknown;
};

export type SiteRender = {
  status: string;
  scripts: number;
  console_errors: number;
  storage_keys: string[];
};

export type SiteRow = {
  host: string;
  url: string;
  heat: number;
  peak_heat: number;
  score_state: string;
  pending_stages: string[];
  findings: { id?: string; title?: string; heat?: number; evidence?: string; remediation?: string; stage?: string }[];
  tech: SiteTech[];
  render: SiteRender | null;
  mode: string;
  scanned_at: string | null;
};

export type SiteRun = {
  run_id: string;
  started_at: string | null;
  finished_at: string | null;
  hosts_scanned: number;
  finding_count: number;
};

function num(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function techFrom(value: unknown): SiteTech[] {
  if (!value || typeof value !== "object") return [];
  const raw = (value as { tech?: unknown }).tech;
  if (!Array.isArray(raw)) return [];
  const out: SiteTech[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const row = item as { name?: unknown; version?: unknown; source?: unknown; eol?: unknown };
    const name = String(row.name || "").trim();
    if (!name) continue;
    out.push({
      name,
      version: String(row.version || "").trim(),
      source: String(row.source || "").trim(),
      eol: row.eol === true,
    });
    if (out.length >= 12) break;
  }
  return out;
}

function renderFrom(value: unknown): SiteRender | null {
  if (!value || typeof value !== "object") return null;
  const raw = (value as { render?: unknown }).render;
  if (!raw || typeof raw !== "object") return null;
  const row = raw as { status?: unknown; scripts?: unknown; console_errors?: unknown; storage_keys?: unknown };
  const status = String(row.status || "");
  if (status !== "rendered" && status !== "challenged") return null;
  const keys = Array.isArray(row.storage_keys)
    ? row.storage_keys.map((item) => String(item)).filter(Boolean).slice(0, 8)
    : [];
  return {
    status,
    scripts: num(row.scripts),
    console_errors: num(row.console_errors),
    storage_keys: keys,
  };
}

export function summarizeRuns(rows: unknown[]): SiteRun[] {
  const out: SiteRun[] = [];
  for (const item of rows) {
    if (!item || typeof item !== "object") continue;
    const row = item as { run_id?: unknown; started_at?: unknown; finished_at?: unknown; hosts_scanned?: unknown; finding_count?: unknown };
    const runId = String(row.run_id || "").trim();
    if (!runId) continue;
    out.push({
      run_id: runId,
      started_at: row.started_at ? String(row.started_at) : null,
      finished_at: row.finished_at ? String(row.finished_at) : null,
      hosts_scanned: num(row.hosts_scanned),
      finding_count: num(row.finding_count),
    });
    if (out.length >= 12) break;
  }
  return out;
}

/** Same weights as the scanner. Header checks stay, capped so they cannot lead the board. */
const WEIGHTS: Record<string, number> = {
  "missing-csp": 1,
  "missing-hsts": 1,
  "missing-nosniff": 1,
  "missing-frame-options": 1,
  "cookie-no-httponly": 1,
  "cookie-no-secure": 1,
  "cookie-no-samesite": 1,
  "cookie-samesite-none": 1,
  "server-banner": 1,
  "csp-unsafe-inline": 2,
  "csp-unsafe-eval": 2,
  "csp-wildcard": 3,
  "cors-credentials-star": 6,
  "tls-expired": 6,
  "tls-soon": 1,
  "exposed-env": 8,
  "exposed-git": 8,
  "exposed-backup": 8,
  "exposed-server-status": 5,
  "exposed-phpinfo": 6,
  "open-directory": 5,
  "private-ip": 3,
  "verbose-error": 4,
  "mixed-content": 3,
  "storage-token": 3,
  "open-admin": 4,
  "secret-in-page": 8,
  "old-library": 6,
  "known-eol": 4,
  "supabase-schema-open": 8,
  "firebase-root-open": 8,
  "dangling-host": 7,
};
const HEADER = new Set([
  "missing-csp",
  "missing-hsts",
  "missing-nosniff",
  "missing-frame-options",
  "cookie-no-httponly",
  "cookie-no-secure",
  "cookie-no-samesite",
  "cookie-samesite-none",
  "server-banner",
]);
const HEADER_CAP = 1;
const MAX_HEAT = 12;

export function heatFromFindings(findings: SiteRow["findings"]): { heat: number; findings: SiteRow["findings"] } {
  const seen = new Set<string>();
  let headerRoom = HEADER_CAP;
  let rest = 0;
  const next = findings.map((item) => {
    const id = String(item.id || "");
    if (!id || seen.has(id) || WEIGHTS[id] == null) return item;
    seen.add(id);
    let applied = WEIGHTS[id];
    if (HEADER.has(id)) {
      applied = Math.min(applied, headerRoom);
      headerRoom -= applied;
    } else {
      rest += applied;
    }
    return { ...item, heat: applied };
  });
  const heat = Math.min(MAX_HEAT, rest + (HEADER_CAP - headerRoom));
  return { heat, findings: next };
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
    const scored = findings.length ? heatFromFindings(findings) : { heat, findings };
    const next: SiteRow = {
      host,
      url: String(row.url || `https://${host}/`),
      heat: scored.heat,
      peak_heat: peak,
      score_state: String(row.score_state || ""),
      pending_stages: pending,
      findings: scored.findings,
      tech: techFrom(row.heat_breakdown),
      render: renderFrom(row.heat_breakdown),
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
    .sort((a, b) => b.heat - a.heat || b.peak_heat - a.peak_heat || a.host.localeCompare(b.host))
    .slice(0, limit);
}
