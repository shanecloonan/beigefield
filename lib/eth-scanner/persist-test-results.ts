/**
 * Persist /test desk results to Supabase (test_scan_runs / findings / triage).
 * Fail soft: never throw to callers — log and return { ok:false }.
 * Service-role only. Defensive findings only — no exploit payloads.
 */

import { createHash } from "node:crypto";
import type { SupabaseClient } from "@supabase/supabase-js";
import { createServiceSupabaseClient, serviceSupabaseConfigured } from "./service-supabase";

export type TestScanKind = "lane-a" | "research" | "engines" | "engines-paste";

export type TriageStatus =
  | "open"
  | "reviewing"
  | "confirmed"
  | "dismissed"
  | "false_positive"
  | "human_yes"
  | "human_no";

export const TRIAGE_STATUSES: readonly TriageStatus[] = [
  "open",
  "reviewing",
  "confirmed",
  "dismissed",
  "false_positive",
  "human_yes",
  "human_no",
] as const;

export type PersistFindingInput = {
  finding_key: string;
  kind?: TestScanKind | "hypothesis";
  address?: string | null;
  engine?: string | null;
  detector?: string | null;
  rule?: string | null;
  layer?: string | null;
  title?: string | null;
  severity?: string | null;
  confidence?: string | null;
  funds_at_risk_class?: string | null;
  triage_score?: number | null;
  triage_status?: TriageStatus;
  invariant_text?: string | null;
  hypothesis_status?: string | null;
  locus?: string | null;
  location?: {
    file?: string | null;
    line?: number | null;
    contract?: string | null;
    function?: string | null;
  } | null;
  evidence?: string | null;
  references?: unknown;
  axes?: unknown;
  tvl_usd?: number | null;
  money_at_risk_usd?: number | null;
  defensive_only?: boolean;
  notes?: unknown;
  raw?: unknown;
};

export type PersistRunInput = {
  kind: TestScanKind;
  address?: string | null;
  fixture?: string | null;
  contract_name?: string | null;
  bytecode_hash?: string | null;
  chain?: string;
  tvl_usd?: number | null;
  money_at_risk_usd?: number | null;
  funds_usd?: number | null;
  funds_breakdown?: unknown;
  funds_status?: string | null;
  funds_checked_at?: string | null;
  invariant_results?: unknown;
  heat_breakdown?: unknown;
  known_safe?: boolean | null;
  deployed_block?: number | null;
  deployed_at?: string | null;
  discovery_source?: string | null;
  bucket?: string | null;
  heat?: number | null;
  status?: string | null;
  dropped?: boolean;
  drop_reason?: string | null;
  src_confidence?: string | null;
  ir_confidence?: string | null;
  contract_class?: string | null;
  scope?: string | null;
  value_movers?: unknown;
  stage_trace?: unknown;
  hypotheses?: unknown;
  pattern_leads?: unknown;
  layers_run?: unknown;
  layers_skipped?: unknown;
  engines?: unknown;
  severity_counts?: unknown;
  notes?: unknown;
  receipt_filename?: string | null;
  receipt_markdown?: string | null;
  duration_ms?: number | null;
  dry_run?: boolean | null;
  live_ingest?: boolean | null;
  persist_remote?: boolean | null;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  findings?: PersistFindingInput[];
  /** Full response / CLI payload — stored as jsonb. */
  raw: unknown;
  /** Optional explicit dedupe key; otherwise derived from kind+address+fixture+raw. */
  dedupe_key?: string;
};

export type PersistResult =
  | {
      ok: true;
      run_id: string;
      findings_count: number;
      dedupe_key: string;
      finding_ids: { finding_key: string; id: string }[];
    }
  | { ok: false; skipped?: boolean; error: string };

export type TriageUpdateResult =
  | { ok: true; finding_id: string; from_status: string; to_status: TriageStatus }
  | { ok: false; skipped?: boolean; error: string };

function asJson(value: unknown): unknown {
  if (value == null) return value ?? null;
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return { _unserializable: true };
  }
}

function stableStringify(value: unknown): string {
  if (value == null) return "null";
  if (typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`).join(",")}}`;
}

export function buildDedupeKey(input: PersistRunInput): string {
  if (input.dedupe_key?.trim()) return input.dedupe_key.trim();
  const basis = [
    input.kind,
    (input.address || "").toLowerCase(),
    input.fixture || "",
    input.receipt_filename || "",
    String(input.duration_ms ?? ""),
    stableStringify(input.raw),
  ].join("|");
  return createHash("sha256").update(basis).digest("hex");
}

function normalizeAddress(raw: string | null | undefined): string | null {
  if (!raw || typeof raw !== "string") return null;
  const s = raw.trim().toLowerCase();
  return /^0x[0-9a-f]{40}$/.test(s) ? s : null;
}

function logPersistError(context: string, err: unknown): void {
  const message = err instanceof Error ? err.message : String(err);
  console.error(`[test-persist] ${context}: ${message}`);
}

export async function persistTestScanRun(
  input: PersistRunInput,
  client?: SupabaseClient | null,
): Promise<PersistResult> {
  if (!serviceSupabaseConfigured() && !client) {
    return { ok: false, skipped: true, error: "supabase service credentials unset" };
  }
  const sb = client ?? createServiceSupabaseClient();
  if (!sb) {
    return { ok: false, skipped: true, error: "supabase service client unavailable" };
  }

  const dedupe_key = buildDedupeKey(input);
  const findings = input.findings ?? [];
  const address = normalizeAddress(input.address);
  const now = new Date().toISOString();

  const runRow = {
    dedupe_key,
    kind: input.kind,
    chain: input.chain || "ethereum",
    address,
    fixture: input.fixture ?? null,
    contract_name: input.contract_name ?? null,
    bytecode_hash: input.bytecode_hash ?? null,
    tvl_usd: input.tvl_usd ?? null,
    money_at_risk_usd: input.money_at_risk_usd ?? input.tvl_usd ?? null,
    funds_usd: input.funds_usd ?? input.tvl_usd ?? null,
    funds_breakdown: asJson(input.funds_breakdown ?? []) ?? [],
    funds_status: input.funds_status ?? null,
    funds_checked_at: input.funds_checked_at ?? null,
    invariant_results: asJson(input.invariant_results ?? []) ?? [],
    heat_breakdown: asJson(input.heat_breakdown ?? {}) ?? {},
    known_safe: Boolean(input.known_safe),
    deployed_block: input.deployed_block ?? null,
    deployed_at: input.deployed_at ?? null,
    discovery_source: input.discovery_source ?? null,
    bucket: input.bucket ?? null,
    heat: input.heat ?? null,
    status: input.status ?? (input.dropped ? "dropped" : input.error ? "error" : "done"),
    dropped: Boolean(input.dropped),
    drop_reason: input.drop_reason ?? null,
    src_confidence: input.src_confidence ?? null,
    ir_confidence: input.ir_confidence ?? null,
    contract_class: input.contract_class ?? null,
    scope: input.scope ?? null,
    value_movers: asJson(input.value_movers ?? []) ?? [],
    stage_trace: asJson(input.stage_trace ?? []) ?? [],
    hypotheses: asJson(input.hypotheses ?? []) ?? [],
    pattern_leads: asJson(input.pattern_leads ?? []) ?? [],
    layers_run: asJson(input.layers_run ?? []) ?? [],
    layers_skipped: asJson(input.layers_skipped ?? []) ?? [],
    engines: asJson(input.engines ?? []) ?? [],
    severity_counts: asJson(input.severity_counts ?? {}) ?? {},
    findings_count: findings.length,
    notes: asJson(input.notes ?? []) ?? [],
    receipt_filename: input.receipt_filename ?? null,
    receipt_markdown: input.receipt_markdown ?? null,
    duration_ms: input.duration_ms ?? null,
    dry_run: input.dry_run ?? null,
    live_ingest: input.live_ingest ?? null,
    persist_remote: input.persist_remote ?? null,
    error: input.error ?? null,
    raw: asJson(input.raw) ?? {},
    started_at: input.started_at ?? now,
    finished_at: input.finished_at ?? now,
  };

  try {
    const { data: run, error: runErr } = await sb
      .from("test_scan_runs")
      .upsert(runRow, { onConflict: "dedupe_key" })
      .select("id")
      .single();

    if (runErr || !run?.id) {
      logPersistError("upsert test_scan_runs", runErr?.message || "no id");
      return { ok: false, error: runErr?.message || "upsert test_scan_runs failed" };
    }

    const run_id = run.id as string;
    if (findings.length === 0) {
      return { ok: true, run_id, findings_count: 0, dedupe_key, finding_ids: [] };
    }

    const findingRows = findings.map((f, i) => {
      const loc = f.location || {};
      return {
        run_id,
        finding_key: f.finding_key || `anon:${i}`,
        kind: f.kind || input.kind,
        address: normalizeAddress(f.address ?? address),
        chain: input.chain || "ethereum",
        engine: f.engine ?? null,
        detector: f.detector ?? null,
        rule: f.rule ?? null,
        layer: f.layer ?? null,
        title: f.title || "",
        severity: f.severity ?? null,
        confidence: f.confidence ?? null,
        funds_at_risk_class: f.funds_at_risk_class ?? null,
        triage_score: f.triage_score ?? null,
        triage_status: f.triage_status ?? "open",
        invariant_text: f.invariant_text ?? null,
        hypothesis_status: f.hypothesis_status ?? null,
        locus: f.locus ?? null,
        location_file: loc.file ?? null,
        location_line: loc.line ?? null,
        location_contract: loc.contract ?? null,
        location_function: loc.function ?? null,
        evidence: f.evidence ?? null,
        references_json: asJson(f.references ?? []) ?? [],
        axes: asJson(f.axes ?? []) ?? [],
        tvl_usd: f.tvl_usd ?? input.tvl_usd ?? null,
        money_at_risk_usd: f.money_at_risk_usd ?? input.money_at_risk_usd ?? input.tvl_usd ?? null,
        defensive_only: f.defensive_only !== false,
        notes: asJson(f.notes ?? []) ?? [],
        raw: asJson(f.raw ?? f) ?? {},
      };
    });

    const { data: savedFindings, error: findErr } = await sb
      .from("test_scan_findings")
      .upsert(findingRows, { onConflict: "run_id,finding_key" })
      .select("id,finding_key");

    if (findErr) {
      logPersistError("upsert test_scan_findings", findErr.message);
      // Run row already saved — soft-fail findings.
      return { ok: true, run_id, findings_count: 0, dedupe_key, finding_ids: [] };
    }

    const finding_ids = (savedFindings ?? []).map((row) => ({
      finding_key: String(row.finding_key),
      id: String(row.id),
    }));

    return { ok: true, run_id, findings_count: findingRows.length, dedupe_key, finding_ids };
  } catch (err) {
    logPersistError("persistTestScanRun", err);
    return { ok: false, error: err instanceof Error ? err.message : "persist failed" };
  }
}

export async function updateFindingTriage(input: {
  finding_id: string;
  to_status: TriageStatus;
  note?: string | null;
  actor?: string | null;
}, client?: SupabaseClient | null): Promise<TriageUpdateResult> {
  if (!TRIAGE_STATUSES.includes(input.to_status)) {
    return { ok: false, error: "invalid triage status" };
  }
  if (!serviceSupabaseConfigured() && !client) {
    return { ok: false, skipped: true, error: "supabase service credentials unset" };
  }
  const sb = client ?? createServiceSupabaseClient();
  if (!sb) {
    return { ok: false, skipped: true, error: "supabase service client unavailable" };
  }

  try {
    const { data: existing, error: readErr } = await sb
      .from("test_scan_findings")
      .select("id,triage_status,run_id")
      .eq("id", input.finding_id)
      .maybeSingle();

    if (readErr) {
      logPersistError("read finding for triage", readErr.message);
      return { ok: false, error: readErr.message };
    }
    if (!existing?.id) {
      return { ok: false, error: "finding not found" };
    }

    const from_status = String(existing.triage_status || "open");
    if (from_status === input.to_status) {
      return { ok: true, finding_id: existing.id, from_status, to_status: input.to_status };
    }

    // Trigger also logs; we still insert an explicit desk event with note/actor.
    const { error: updErr } = await sb
      .from("test_scan_findings")
      .update({ triage_status: input.to_status })
      .eq("id", existing.id);

    if (updErr) {
      logPersistError("update triage_status", updErr.message);
      return { ok: false, error: updErr.message };
    }

    const verdict_kind =
      input.to_status === "human_yes" || input.to_status === "confirmed"
        ? "true"
        : input.to_status === "human_no" || input.to_status === "false_positive" || input.to_status === "dismissed"
          ? "false_positive"
          : input.to_status === "reviewing"
            ? "needs_info"
            : null;

    {
      const { error: evErr } = await sb.from("test_triage_events").insert({
        finding_id: existing.id,
        run_id: existing.run_id,
        from_status,
        to_status: input.to_status,
        actor: input.actor || "desk",
        note: input.note || null,
        verdict_kind,
        raw: { source: "api" },
      });
      if (evErr) logPersistError("insert triage event", evErr.message);
    }

    return { ok: true, finding_id: existing.id, from_status, to_status: input.to_status };
  } catch (err) {
    logPersistError("updateFindingTriage", err);
    return { ok: false, error: err instanceof Error ? err.message : "triage update failed" };
  }
}

export type HistoryOptions = {
  kind?: TestScanKind | null;
  address?: string | null;
  limit?: number;
};

export async function loadTestScanHistory(
  opts: HistoryOptions = {},
  client?: SupabaseClient | null,
): Promise<{
  ok: boolean;
  skipped?: boolean;
  error?: string;
  runs: Record<string, unknown>[];
  findings: Record<string, unknown>[];
}> {
  if (!serviceSupabaseConfigured() && !client) {
    return { ok: false, skipped: true, error: "supabase service credentials unset", runs: [], findings: [] };
  }
  const sb = client ?? createServiceSupabaseClient();
  if (!sb) {
    return { ok: false, skipped: true, error: "supabase service client unavailable", runs: [], findings: [] };
  }

  const limit = Math.min(100, Math.max(1, opts.limit ?? 40));
  const runColumns =
        "id,dedupe_key,kind,chain,address,fixture,contract_name,tvl_usd,money_at_risk_usd,funds_usd,funds_breakdown,funds_status,funds_checked_at,bucket,heat,heat_breakdown,status,dropped,drop_reason,src_confidence,ir_confidence,contract_class,scope,findings_count,severity_counts,duration_ms,receipt_filename,error,created_at,finished_at";
  const feedColumns = `${runColumns},discovery_source,candidate_reason,tier,notes`;
  try {
    let runsQ = sb
      .from("test_scan_runs")
      .select(feedColumns)
      .order("created_at", { ascending: false })
      .limit(limit);

    if (opts.kind) runsQ = runsQ.eq("kind", opts.kind);
    if (opts.address) {
      const addr = normalizeAddress(opts.address);
      if (addr) runsQ = runsQ.eq("address", addr);
    }

    let { data: runs, error: runsErr } = await runsQ;
    if (runsErr && /candidate_reason|tier|discovery_source/i.test(runsErr.message)) {
      // Migration not applied yet — history still loads without the feed columns.
      let fallbackQ = sb
        .from("test_scan_runs")
        .select(runColumns)
        .order("created_at", { ascending: false })
        .limit(limit);
      if (opts.kind) fallbackQ = fallbackQ.eq("kind", opts.kind);
      if (opts.address) {
        const addr = normalizeAddress(opts.address);
        if (addr) fallbackQ = fallbackQ.eq("address", addr);
      }
      const fallback = await fallbackQ;
      runs = fallback.data;
      runsErr = fallback.error;
    }
    if (runsErr) {
      logPersistError("load test_scan_runs", runsErr.message);
      return { ok: false, error: runsErr.message, runs: [], findings: [] };
    }

    const runIds = (runs ?? []).map((r) => r.id).filter(Boolean);
    let findings: Record<string, unknown>[] = [];
    if (runIds.length) {
      const { data: findingRows, error: findErr } = await sb
        .from("test_scan_findings")
        .select(
          "id,run_id,finding_key,kind,address,engine,detector,rule,layer,title,severity,confidence,funds_at_risk_class,triage_score,triage_status,invariant_text,hypothesis_status,evidence,tvl_usd,money_at_risk_usd,created_at,updated_at",
        )
        .in("run_id", runIds)
        .order("created_at", { ascending: false })
        .limit(Math.min(400, limit * 10));

      if (findErr) {
        logPersistError("load test_scan_findings", findErr.message);
      } else {
        findings = findingRows ?? [];
      }
    }

    return { ok: true, runs: runs ?? [], findings };
  } catch (err) {
    logPersistError("loadTestScanHistory", err);
    return {
      ok: false,
      error: err instanceof Error ? err.message : "history load failed",
      runs: [],
      findings: [],
    };
  }
}

/** Map a successful Lane A API response into a persist payload. */
export function laneAPersistInput(body: {
  result: {
    address: string;
    bucket: string | null;
    dropped: boolean;
    drop_reason: string | null;
    heat: number | null;
    src_confidence: string | null;
    ir_confidence: string | null;
    value_movers?: string[];
    contract_class?: string | null;
    scope?: string | null;
    notes?: string[];
    funds_usd?: number | null;
    funds_breakdown?: unknown;
    funds_status?: string | null;
    funds_checked_at?: string | null;
    stage_trace?: unknown;
    invariant_results?: unknown;
    heat_breakdown?: unknown;
    known_safe?: boolean;
    contract_name?: string | null;
    pattern_leads?: unknown;
    hypotheses?: unknown;
  };
  fixture?: string | null;
  dry_run?: boolean;
  live_ingest?: boolean;
  persist_remote?: boolean;
  duration_ms?: number;
  receipt_markdown?: string | null;
  receipt_filename?: string | null;
  tvl?: number | null;
}): PersistRunInput {
  const r = body.result;
  const funds = r.funds_usd ?? body.tvl ?? null;
  return {
    kind: "lane-a",
    address: r.address,
    fixture: body.fixture ?? null,
    contract_name: r.contract_name ?? null,
    tvl_usd: funds,
    money_at_risk_usd: funds,
    funds_usd: funds,
    funds_breakdown: r.funds_breakdown ?? [],
    funds_status: r.funds_status ?? null,
    funds_checked_at: r.funds_checked_at ?? null,
    invariant_results: r.invariant_results ?? [],
    heat_breakdown: r.heat_breakdown ?? {},
    known_safe: Boolean(r.known_safe),
    bucket: r.bucket,
    heat: r.heat,
    status: r.dropped ? "dropped" : "done",
    dropped: r.dropped,
    drop_reason: r.drop_reason,
    src_confidence: r.src_confidence,
    ir_confidence: r.ir_confidence,
    contract_class: r.contract_class ?? null,
    scope: r.scope ?? null,
    value_movers: r.value_movers ?? [],
    stage_trace: r.stage_trace ?? [],
    pattern_leads: r.pattern_leads ?? [],
    hypotheses: r.hypotheses ?? [],
    notes: r.notes ?? [],
    receipt_filename: body.receipt_filename ?? null,
    receipt_markdown: body.receipt_markdown ?? null,
    duration_ms: body.duration_ms ?? null,
    dry_run: body.dry_run ?? null,
    live_ingest: body.live_ingest ?? null,
    persist_remote: body.persist_remote ?? null,
    findings: [],
    raw: body,
    // Same address re-scan updates the prior lane-a row (history via triage events).
    dedupe_key: `lane-a:${(r.address || "").toLowerCase()}`,
  };
}

/** Map a research API response into a persist payload. */
export function researchPersistInput(body: {
  result: {
    address: string;
    gated: boolean;
    gate_reason: string;
    role: string | null;
    scope: string | null;
    layers_run: string[];
    layers_skipped: unknown[];
    findings: Array<{
      id: string;
      severity: string;
      layer: string;
      title: string;
      evidence: string;
      address: string;
      detector: string;
      defensive_only?: boolean;
    }>;
    notes: string[];
  };
  fixture?: string | null;
  dry_run?: boolean;
  duration_ms?: number;
  receipt_markdown?: string | null;
  receipt_filename?: string | null;
}): PersistRunInput {
  const r = body.result;
  return {
    kind: "research",
    address: r.address,
    fixture: body.fixture ?? null,
    status: r.gated ? "gated" : "done",
    scope: r.scope,
    layers_run: r.layers_run,
    layers_skipped: r.layers_skipped,
    notes: r.notes,
    receipt_filename: body.receipt_filename ?? null,
    receipt_markdown: body.receipt_markdown ?? null,
    duration_ms: body.duration_ms ?? null,
    dry_run: body.dry_run ?? true,
    findings: (r.findings || []).map((f) => ({
      finding_key: f.id || `${f.detector}:${f.title}`,
      kind: "research" as const,
      address: f.address || r.address,
      detector: f.detector,
      layer: f.layer,
      title: f.title,
      severity: f.severity,
      evidence: f.evidence,
      defensive_only: f.defensive_only !== false,
      raw: f,
    })),
    raw: body,
  };
}

/** Map an engines desk API response into a persist payload. */
export function enginesPersistInput(body: {
  mode: "engines" | "engines-paste";
  fixture?: string | null;
  engine?: string | null;
  findings?: Array<{
    id: string;
    engine: string;
    rule: string;
    title: string;
    severity: string;
    confidence: string;
    class: string;
    location?: {
      file?: string | null;
      line?: number | null;
      contract?: string | null;
      function?: string | null;
    };
    evidence?: string;
    references?: unknown;
    triage?: number;
    defensive_only?: boolean;
  }>;
  runs?: unknown;
  severity_counts?: unknown;
  duration_ms?: number | null;
  warning?: string | null;
  raw: unknown;
}): PersistRunInput {
  const findings = body.findings ?? [];
  return {
    kind: body.mode,
    fixture: body.fixture ?? null,
    status: "done",
    engines: body.engine ? [body.engine] : body.runs ?? [],
    severity_counts: body.severity_counts ?? {},
    notes: body.warning ? [body.warning] : [],
    duration_ms: body.duration_ms ?? null,
    findings: findings.map((f) => ({
      finding_key: f.id,
      kind: body.mode,
      engine: f.engine,
      rule: f.rule,
      title: f.title,
      severity: f.severity,
      confidence: f.confidence,
      funds_at_risk_class: f.class,
      triage_score: f.triage ?? null,
      location: f.location ?? null,
      evidence: f.evidence ?? null,
      references: f.references ?? [],
      defensive_only: f.defensive_only !== false,
      raw: f,
    })),
    raw: body.raw,
  };
}
