"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DEFAULT_LOOP_GAP_MS,
  MAX_LOOP_GAP_MS,
  MIN_LOOP_GAP_MS,
  RANDOM_HISTORY_CAP,
  SESSION_ROW_CAP,
  clampLoopGapMs,
  isEtherscanRateLimit,
  pushCapped,
  runContinuousRandom,
  type RandomLoopSample,
} from "@/lib/eth-scanner/random-loop";
import EnginesPanel from "./engines-panel";

type Bucket =
  | "lane-a-cool"
  | "lane-b-queue"
  | "manual-review"
  | "human-no-candidate"
  | "human-yes-candidate";

type FundsAsset = {
  symbol: string;
  usd?: number;
  amount?: number;
  kind?: string;
  address?: string | null;
};

type Target = {
  address: string;
  bytecode_hash: string | null;
  tvl_usd: number | string | null;
  status: string | null;
  src_confidence: string | null;
  ir_confidence: string | null;
  heat: number | null;
  bucket: Bucket | null;
  updated_at: string | null;
  funds_usd?: number | string | null;
  funds_breakdown?: FundsAsset[] | null;
  funds_status?: string | null;
  funds_checked_at?: string | null;
};

type FixtureOpt = { id: string; label: string };

type HistoryRun = {
  id: string;
  kind: string;
  address: string | null;
  fixture: string | null;
  bucket: string | null;
  heat: number | null;
  status: string | null;
  findings_count: number | null;
  tvl_usd?: number | null;
  money_at_risk_usd?: number | null;
  duration_ms?: number | null;
  created_at: string;
};

type HistoryFinding = {
  id: string;
  run_id: string;
  finding_key: string;
  title: string;
  severity: string | null;
  triage_status: string;
  funds_at_risk_class?: string | null;
  address?: string | null;
};

type PrecisionStats = {
  flagged?: number | null;
  confirmed_true?: number | null;
  confirmed_false?: number | null;
  needs_info?: number | null;
  open_flags?: number | null;
  precision?: number | null;
};

type BenchmarkStats = {
  labeled?: number;
  false_positive?: number;
  true_negative?: number;
  true_positive?: number;
  false_negative?: number;
  precision?: number | null;
  recall?: number | null;
  false_positive_rate?: number | null;
  passes_baseline?: boolean;
};

type Feed = {
  ok: boolean;
  dry_run: boolean;
  live_ingest?: boolean;
  persist_remote?: boolean;
  buckets: Bucket[];
  counts: Record<string, number>;
  targets: Target[];
  results: { address: string; bucket: string; heat: number; notes: string | null; created_at: string }[];
  history?: { runs: HistoryRun[]; findings: HistoryFinding[]; error?: string };
  precision?: PrecisionStats | null;
  benchmark?: BenchmarkStats | null;
  alerts?: { id?: string; address: string; kind: string; detail: string; funds_usd?: number | null; created_at?: string }[];
  fixtures?: FixtureOpt[];
  note?: string;
  ephemeral_store?: boolean;
};

/** A Lane A run kept client-side for this tab (serverless /tmp is per-instance). */
type SessionRow = Target & {
  key: string;
  fixture: string | null;
  receipt_markdown: string | null;
  receipt_filename: string | null;
  ran_at: number;
};

type RunResult = {
  address: string;
  bucket: string | null;
  dropped: boolean;
  drop_reason: string | null;
  heat: number | null;
  src_confidence: string | null;
  ir_confidence: string | null;
  value_movers: string[];
  contract_class: string | null;
  scope: string | null;
  notes: string[];
  funds_usd?: number | null;
  funds_breakdown?: FundsAsset[];
  funds_status?: string | null;
  funds_checked_at?: string | null;
  known_safe?: boolean;
  deployed_block?: number | null;
  deployed_at?: string | null;
  engine_leads?: Array<Record<string, unknown>> | null;
  confirmed_findings?: Array<Record<string, unknown>> | null;
  engine_timing?: Record<string, unknown> | null;
  heat_breakdown?: Record<string, unknown> | null;
};

type PersistInfo = {
  ok: boolean;
  skipped?: boolean;
  error?: string;
  run_id?: string;
  findings_count?: number;
};

type RunResponse = {
  ok: boolean;
  error?: string;
  dry_run?: boolean;
  live_ingest?: boolean;
  persist_remote?: boolean;
  fixture?: string | null;
  note?: string;
  result?: RunResult;
  receipt_url?: string;
  receipt_markdown?: string | null;
  receipt_filename?: string | null;
  duration_ms?: number;
  persist?: PersistInfo;
};

type LoopState = "idle" | "running" | "stopping" | "paused";

type LoopHistoryRow = {
  key: string;
  address: string;
  contract_name: string | null;
  bucket: string | null;
  heat: number | null;
  funds_usd?: number | null;
  funds_status?: string | null;
  dropped?: boolean;
  drop_reason?: string | null;
};

type RandomSample = {
  ok: boolean;
  error?: string;
  kind?: string;
  address?: string;
  contract_name?: string | null;
  compiler?: string | null;
  block_number?: number;
  strategy?: string;
  source_checks?: number;
  blocks_tried?: number;
  note?: string;
};

type Tab = "lane-a" | "research" | "engines";

type ResearchFinding = {
  id: string;
  severity: string;
  layer: string;
  title: string;
  evidence: string;
  address: string;
  detector: string;
  defensive_only: boolean;
};

type ResearchResult = {
  address: string;
  gated: boolean;
  gate_reason: string;
  role: string | null;
  scope: string | null;
  layers_run: string[];
  layers_skipped: { layer: string; reason: string }[];
  findings: ResearchFinding[];
  notes: string[];
  receipt_md_path: string | null;
  receipt_json_path: string | null;
  defensive_only: boolean;
};

type ResearchResponse = {
  ok: boolean;
  error?: string;
  dry_run?: boolean;
  fixture?: string | null;
  note?: string;
  result?: ResearchResult;
  receipt_url?: string;
  receipt_markdown?: string | null;
  receipt_filename?: string | null;
  duration_ms?: number;
  persist?: PersistInfo;
};

type ResearchFeed = {
  ok: boolean;
  fixtures?: FixtureOpt[];
  receipts?: { filename: string; address: string; mtime: number }[];
  latest?: {
    address: string;
    filename: string;
    gated: boolean;
    gate_reason: string;
    role: string | null;
    scope: string | null;
    layers_run: string[];
    layers_skipped: { layer?: string; reason?: string }[];
    findings_count: number;
    findings: ResearchFinding[];
    notes: string[];
    receipt_url: string | null;
    stack_version: string | null;
  } | null;
  note?: string;
  python_runtime?: { available?: boolean; error?: string };
};

const BUCKET_META: Record<Bucket, { label: string; hint: string; cls: string }> = {
  "lane-a-cool": {
    label: "Lane A cool",
    hint: "High/usable IR, movers gated or none",
    cls: "border-brand-700 text-brand-200",
  },
  "lane-b-queue": {
    label: "Lane B queue",
    hint: "Heat / TVL / weirdness — deep pass",
    cls: "border-amber-700/70 text-amber-200",
  },
  "manual-review": {
    label: "Manual review",
    hint: "Low IR or ambiguous cheap check — not discarded",
    cls: "border-rose-700/70 text-rose-200",
  },
  "human-no-candidate": {
    label: "Human no",
    hint: "High-confidence all-clear — human stamps no",
    cls: "border-emerald-800 text-emerald-200",
  },
  "human-yes-candidate": {
    label: "Human yes",
    hint: "BROKEN locus — human stamps yes after path verify",
    cls: "border-gold/50 text-gold",
  },
};

const SEV_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
const SEV_CLS: Record<string, string> = {
  critical: "text-rose-200",
  high: "text-rose-300",
  medium: "text-amber-200",
  low: "text-brand-200",
  info: "text-brand-400",
};

export function downloadMarkdown(markdown: string, filename: string) {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".md") ? filename : `${filename}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Seconds since `active` flipped on; 0 when idle. */
function useElapsed(active: boolean): number {
  const [secs, setSecs] = useState(0);
  const start = useRef(0);
  useEffect(() => {
    if (!active) return;
    start.current = Date.now();
    const id = setInterval(() => setSecs(Math.floor((Date.now() - start.current) / 1000)), 250);
    return () => {
      clearInterval(id);
      setSecs(0);
    };
  }, [active]);
  return active ? secs : 0;
}

function fmtMs(ms?: number): string | null {
  if (ms == null || !Number.isFinite(ms)) return null;
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/;
const DEMO_ADDRESS = "0x1111111111111111111111111111111111111111";

const inputCls =
  "rounded-md bg-brand-900 border border-brand-800 px-3 py-2 text-sm text-brand-100 placeholder:text-brand-600 focus:outline-none focus:border-gold/50";
const btnPrimary =
  "px-4 py-2 text-[11px] tracking-[0.15em] uppercase font-semibold rounded-md text-brand-950 bg-gold hover:bg-gold/90 disabled:opacity-50 disabled:cursor-not-allowed";
const btnSecondary =
  "px-4 py-2 text-[11px] tracking-[0.15em] uppercase font-semibold rounded-md border border-brand-700 text-brand-200 hover:bg-brand-900 disabled:opacity-50 disabled:cursor-not-allowed";

export default function TestApp() {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bucket, setBucket] = useState<Bucket | "all">("all");
  const [q, setQ] = useState("");
  const [address, setAddress] = useState("");
  const [fixture, setFixture] = useState("");
  const [running, setRunning] = useState(false);
  const [phase, setPhase] = useState<"sample" | "scan" | "wait" | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<RunResponse | null>(null);
  const [randomPick, setRandomPick] = useState<RandomSample | null>(null);
  const [loopState, setLoopState] = useState<LoopState>("idle");
  const [loopCount, setLoopCount] = useState(0);
  const [loopMessage, setLoopMessage] = useState<string | null>(null);
  const [loopHistory, setLoopHistory] = useState<LoopHistoryRow[]>([]);
  const [waitLeft, setWaitLeft] = useState<number | null>(null);
  const [gapSec, setGapSec] = useState(DEFAULT_LOOP_GAP_MS / 1000);
  const busy = useRef(false);
  const loopActive = useRef(false);
  const stopRef = useRef(false);
  const gapRef = useRef(DEFAULT_LOOP_GAP_MS / 1000);
  const pickRef = useRef<RandomSample | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("lane-a");
  const [researchFixture, setResearchFixture] = useState("erc4626_vault");
  const [researchAddress, setResearchAddress] = useState("");
  const [researchRunning, setResearchRunning] = useState(false);
  const [researchError, setResearchError] = useState<string | null>(null);
  const [lastResearch, setLastResearch] = useState<ResearchResponse | null>(null);
  const [researchFeed, setResearchFeed] = useState<ResearchFeed | null>(null);
  const [uploadedReceipt, setUploadedReceipt] = useState<ResearchResult | null>(null);
  const [session, setSession] = useState<SessionRow[]>([]);
  const elapsed = useElapsed(running);

  const load = useCallback(async () => {
    setError(null);
    const params = new URLSearchParams();
    if (bucket !== "all") params.set("bucket", bucket);
    const res = await fetch(`/api/test?${params.toString()}`, { cache: "no-store" });
    if (!res.ok) {
      setError(`HTTP ${res.status}`);
      return;
    }
    setFeed((await res.json()) as Feed);
  }, [bucket]);

  useEffect(() => {
    void load();
  }, [load]);

  // Serverless dry-run: each request may hit a fresh instance with an empty
  // work dir, so the server table can't reflect the run you just did. Use the
  // session queue there (and whenever the server has nothing to show).
  const useSession = Boolean(feed?.ephemeral_store) || (feed?.targets?.length ?? 0) === 0;
  const baseRows: (Target | SessionRow)[] = useMemo(() => {
    if (!useSession) return feed?.targets ?? [];
    return bucket === "all" ? session : session.filter((r) => r.bucket === bucket);
  }, [useSession, feed, session, bucket]);
  const counts = useMemo(() => {
    if (!useSession) return feed?.counts ?? {};
    const out: Record<string, number> = {};
    for (const r of session) if (r.bucket) out[r.bucket] = (out[r.bucket] ?? 0) + 1;
    return out;
  }, [useSession, feed, session]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const filtered = !needle
      ? baseRows
      : baseRows.filter((t) =>
          [t.address, t.bucket, t.src_confidence, t.ir_confidence, t.bytecode_hash]
            .filter(Boolean)
            .some((v) => String(v).toLowerCase().includes(needle)),
        );
    // Default sort: confirmed heat desc, then funds desc.
    return [...filtered].sort((a, b) => {
      const ha = Number(a.heat ?? 0);
      const hb = Number(b.heat ?? 0);
      if (hb !== ha) return hb - ha;
      const fa = Number(a.funds_usd ?? a.tvl_usd ?? 0);
      const fb = Number(b.funds_usd ?? b.tvl_usd ?? 0);
      return fb - fa;
    });
  }, [baseRows, q]);

  const fixtures = feed?.fixtures ?? [];
  const dryRun = feed?.dry_run ?? true;
  const liveIngest = feed?.live_ingest ?? false;

  const selectTarget = useCallback((addr: string) => {
    setAddress(addr);
    setSelected(addr.toLowerCase());
    setFixture("");
    setRunError(null);
  }, []);

  const loadResearch = useCallback(async () => {
    try {
      const res = await fetch("/api/test/research", { cache: "no-store" });
      if (!res.ok) return;
      setResearchFeed((await res.json()) as ResearchFeed);
    } catch {
      /* keep last feed */
    }
  }, []);

  useEffect(() => {
    if (tab === "research") void loadResearch();
  }, [tab, loadResearch]);

  const runResearch = useCallback(async () => {
    const addr = researchAddress.trim();
    const fx = researchFixture;
    if (!fx && !ADDRESS_RE.test(addr)) {
      setResearchError("Enter a 0x address (40 hex chars) or pick a local fixture.");
      return;
    }
    setResearchRunning(true);
    setResearchError(null);
    setLastResearch(null);
    setUploadedReceipt(null);
    try {
      const res = await fetch("/api/test/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({
          address: addr || undefined,
          fixture: fx || undefined,
        }),
      });
      const body = (await res.json()) as ResearchResponse;
      if (!body.ok) {
        setResearchError(body.error || `HTTP ${res.status}`);
        setLastResearch(body);
        return;
      }
      setLastResearch(body);
      if (body.result?.address) setResearchAddress(body.result.address);
      await loadResearch();
    } catch (err) {
      setResearchError(err instanceof Error ? err.message : "Research run failed");
    } finally {
      setResearchRunning(false);
    }
  }, [researchAddress, researchFixture, loadResearch]);

  const runScan = useCallback(async (
    override?: { address?: string; fixture?: string },
    opts?: { locked?: boolean; keepPrevious?: boolean },
  ): Promise<RunResponse | null> => {
    if (!opts?.locked) {
      if (busy.current || loopActive.current) return null;
      busy.current = true;
      setRandomPick(null);
      setPhase("scan");
    }
    const addr = (override?.address ?? address).trim();
    const fx = override?.fixture ?? fixture;
    if (!fx && !ADDRESS_RE.test(addr)) {
      setRunError("Enter a 0x address (40 hex chars) or pick a local fixture.");
      if (!opts?.locked) {
        busy.current = false;
        setPhase(null);
      }
      return null;
    }
    setRunning(true);
    setRunError(null);
    if (!opts?.keepPrevious) setLastRun(null);
    if (addr) setSelected(addr.toLowerCase());
    try {
      const res = await fetch("/api/test/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({
          address: addr || undefined,
          fixture: fx || undefined,
        }),
      });
      const body = (await res.json()) as RunResponse;
      if (!body.ok) {
        setRunError(body.error || `HTTP ${res.status}`);
        setLastRun(body);
        return body;
      }
      setLastRun(body);
      if (body.result) {
        const r = body.result;
        const key = body.fixture ? `fixture:${body.fixture}` : r.address.toLowerCase();
        const row: SessionRow = {
          key,
          fixture: body.fixture ?? null,
          address: r.address,
          bytecode_hash: null,
          tvl_usd: r.funds_usd ?? null,
          status: r.dropped ? `dropped${r.drop_reason ? ` · ${r.drop_reason}` : ""}` : "scanned",
          src_confidence: r.src_confidence,
          ir_confidence: r.ir_confidence,
          heat: r.heat,
          bucket: (r.bucket as Bucket | null) ?? null,
          updated_at: new Date().toISOString(),
          funds_usd: r.funds_usd ?? null,
          funds_breakdown: r.funds_breakdown ?? null,
          funds_status: r.funds_status ?? null,
          funds_checked_at: r.funds_checked_at ?? null,
          receipt_markdown: body.receipt_markdown ?? null,
          receipt_filename: body.receipt_filename ?? null,
          ran_at: Date.now(),
        };
        setSession((prev) => pushCapped(prev.filter((p) => p.key !== key), row, SESSION_ROW_CAP));
        setSelected(key);
        if (!body.fixture) setAddress(r.address);
      }
      await load();
      return body;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Run failed";
      setRunError(message);
      return { ok: false, error: message };
    } finally {
      setRunning(false);
      if (!opts?.locked) {
        busy.current = false;
        setPhase(null);
      }
    }
  }, [address, fixture, load]);

  const sampleForLoop = useCallback(async (): Promise<RandomLoopSample> => {
    if (stopRef.current) return { ok: false, kind: "pause", error: "Stopped." };
    setPhase("sample");
    setRunning(true);
    setWaitLeft(null);
    setFixture("");
    try {
      const res = await fetch("/api/test/random", { method: "POST", cache: "no-store" });
      let body: RandomSample;
      try {
        body = (await res.json()) as RandomSample;
      } catch {
        return { ok: false, kind: "pause", error: `Couldn't read the contract sample (HTTP ${res.status}).` };
      }
      if (!res.ok || !body.ok || !body.address || !ADDRESS_RE.test(body.address)) {
        const error = body.error || `Couldn't pick a verified contract (HTTP ${res.status}).`;
        const rateLimited = res.status === 429 || body.kind === "rate_limit" || isEtherscanRateLimit(error);
        if (rateLimited) return { ok: false, kind: "rate_limit", error };
        if (res.status === 404 || body.kind === "none") return { ok: false, kind: "retry", error };
        return { ok: false, kind: "pause", error };
      }
      pickRef.current = body;
      setRandomPick(body);
      setAddress(body.address);
      setSelected(body.address.toLowerCase());
      return { ok: true, address: body.address };
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't reach Etherscan.";
      if (isEtherscanRateLimit(message)) return { ok: false, kind: "rate_limit", error: message };
      return { ok: false, kind: "pause", error: message };
    }
  }, []);

  const scanForLoop = useCallback(async (addr: string) => {
    const picked = pickRef.current;
    const body = await runScan({ address: addr, fixture: "" }, { locked: true, keepPrevious: true });
    if (!body) return { ok: false, error: "The scan did not start." };
    const noteText = [
      body.error || "",
      body.result?.drop_reason || "",
      ...(body.result?.notes || []),
    ].join("\n");
    const rateLimited = isEtherscanRateLimit(noteText);
    if (body.ok && body.result) {
      setLoopHistory((prev) => pushCapped(prev, {
        key: `${body.result!.address}:${Date.now()}`,
        address: body.result!.address,
        contract_name: picked?.contract_name ?? null,
        bucket: body.result!.bucket,
        heat: body.result!.heat,
        funds_usd: body.result!.funds_usd ?? null,
        funds_status: body.result!.funds_status ?? null,
        dropped: body.result!.dropped,
        drop_reason: body.result!.drop_reason,
      }, RANDOM_HISTORY_CAP));
    }
    if (!body.ok) return { ok: false, rateLimited, error: body.error || "The scan failed." };
    if (rateLimited) {
      return { ok: true, rateLimited: true, error: "Etherscan rate limit during Lane A ingest. Paused so the loop does not keep calling." };
    }
    return { ok: true };
  }, [runScan]);

  const startLoop = useCallback(async () => {
    if (loopActive.current || busy.current) return;
    loopActive.current = true;
    stopRef.current = false;
    setLoopState("running");
    setLoopMessage(null);
    setRunError(null);
    setWaitLeft(null);
    try {
      const outcome = await runContinuousRandom({
        gapMs: () => clampLoopGapMs(gapRef.current * 1000),
        stop: () => stopRef.current,
        sample: sampleForLoop,
        scan: scanForLoop,
        sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
        onScanned: () => setLoopCount((count) => count + 1),
        onWaitTick: (remainingMs) => {
          setPhase("wait");
          setWaitLeft(Math.ceil(remainingMs / 1000));
        },
      });
      if (outcome.reason === "stopped") {
        setLoopState("idle");
        setLoopMessage("Stopped. The next contract waits until you press Start.");
      } else {
        setLoopState("paused");
        setLoopMessage(outcome.message);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "The continuous run stopped.";
      setLoopMessage(message);
      setLoopState("paused");
      setRunError(message);
    } finally {
      loopActive.current = false;
      stopRef.current = false;
      busy.current = false;
      setRunning(false);
      setPhase(null);
      setWaitLeft(null);
    }
  }, [sampleForLoop, scanForLoop]);

  const stopLoop = useCallback(() => {
    if (!loopActive.current) return;
    stopRef.current = true;
    setLoopState("stopping");
    setWaitLeft(null);
  }, []);

  useEffect(() => () => {
    stopRef.current = true;
  }, []);

  const loopBusy = loopState === "running" || loopState === "stopping";

  return (
    <main className="min-h-screen bg-brand-950 text-brand-100">
      <div className="max-w-[1100px] mx-auto px-5 sm:px-8 pt-10 pb-16">
        <Link
          href="/"
          className="inline-block mb-10 text-[11px] tracking-[0.2em] uppercase text-brand-400 hover:text-gold"
        >
          ← Beigefield
        </Link>
        <p className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold mb-2">
          Beigefield · Ethereum only · /test
        </p>
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight text-brand-50">
          Invariant scanner triage
        </h1>
        <p className="mt-3 max-w-2xl text-sm text-brand-400 leading-relaxed">
          Lane A/B buckets. Automation never stamps{" "}
          <span className="text-brand-200">yes</span>. Low IR / decompile confidence
          stays in <span className="text-rose-200">manual-review</span> — never a silent no.
          No exploit payloads. Humans close BROKEN paths in prose.
        </p>

        <DeskStatus feed={feed} />
        {error && (
          <p className="mt-4 text-sm text-rose-300">
            Couldn&apos;t load the queue ({error}).{" "}
            <button type="button" onClick={() => void load()} className="underline underline-offset-2 hover:text-rose-200">
              Retry
            </button>
          </p>
        )}

        <div className="mt-8 flex gap-2" role="tablist" aria-label="Scanner mode">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "lane-a"}
            onClick={() => setTab("lane-a")}
            className={`px-4 py-2 text-[11px] tracking-[0.15em] uppercase font-semibold rounded-md border ${
              tab === "lane-a"
                ? "border-gold/60 text-gold bg-gold/10"
                : "border-brand-700 text-brand-300 hover:bg-brand-900"
            }`}
          >
            Lane A
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "research"}
            onClick={() => setTab("research")}
            className={`px-4 py-2 text-[11px] tracking-[0.15em] uppercase font-semibold rounded-md border ${
              tab === "research"
                ? "border-gold/60 text-gold bg-gold/10"
                : "border-brand-700 text-brand-300 hover:bg-brand-900"
            }`}
          >
            Research
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "engines"}
            onClick={() => setTab("engines")}
            className={`px-4 py-2 text-[11px] tracking-[0.15em] uppercase font-semibold rounded-md border ${
              tab === "engines"
                ? "border-gold/60 text-gold bg-gold/10"
                : "border-brand-700 text-brand-300 hover:bg-brand-900"
            }`}
          >
            Engines
          </button>
        </div>

        {tab === "lane-a" && (
        <>
        <form
          className="mt-8 rounded-lg border border-brand-800/80 bg-brand-900/30 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (loopBusy) return;
            void runScan();
          }}
        >
          <div className="flex flex-col sm:flex-row gap-3 sm:items-end">
            <label className="flex-1 min-w-0">
              <span className="block text-[10px] tracking-[0.14em] uppercase text-brand-500 mb-1.5">
                Address
              </span>
              <input
                value={address}
                onChange={(e) => {
                  setAddress(e.target.value);
                  setSelected(e.target.value.trim().toLowerCase() || null);
                }}
                placeholder="0x… contract to scan"
                spellCheck={false}
                autoComplete="off"
                className={`w-full font-mono text-[13px] ${inputCls}`}
              />
            </label>
            <label className="sm:w-56">
              <span className="block text-[10px] tracking-[0.14em] uppercase text-brand-500 mb-1.5">
                Local fixture
              </span>
              <select
                value={fixture}
                onChange={(e) => setFixture(e.target.value)}
                className={`w-full ${inputCls}`}
              >
                <option value="">None — ingest address</option>
                {fixtures.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.label}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" disabled={running || loopBusy} className={btnPrimary} aria-busy={running && !loopBusy}>
              {running && phase === "scan" && !loopBusy ? "Running…" : "Run"}
            </button>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={loopBusy || running}
              onClick={() => void startLoop()}
              className={btnPrimary}
            >
              {loopState === "paused" ? "Resume" : "Start"}
            </button>
            <button
              type="button"
              disabled={!loopBusy}
              onClick={stopLoop}
              className={btnSecondary}
            >
              {loopState === "stopping" ? "Stopping…" : "Stop"}
            </button>
            <label className="flex items-center gap-2 text-[11px] text-brand-400">
              <span className="tracking-[0.12em] uppercase text-brand-500">Seconds between scans</span>
              <input
                type="number"
                min={MIN_LOOP_GAP_MS / 1000}
                max={MAX_LOOP_GAP_MS / 1000}
                step={1}
                value={gapSec}
                disabled={loopBusy}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  if (!Number.isFinite(n)) return;
                  const next = Math.min(MAX_LOOP_GAP_MS / 1000, Math.max(MIN_LOOP_GAP_MS / 1000, Math.round(n)));
                  gapRef.current = next;
                  setGapSec(next);
                }}
                className={`w-16 font-mono text-[13px] ${inputCls}`}
              />
            </label>
            <span className="text-[11px] text-brand-500 leading-relaxed">
              Start keeps sampling a verified contract and running Lane A, one at a time.
              Stop finishes the scan in progress and does not start another.
              {loopCount > 0 ? ` ${loopCount} scanned this session.` : ""}
            </span>
          </div>
          {fixtures.length > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <span className="text-[10px] tracking-[0.14em] uppercase text-brand-500 mr-1">
                {liveIngest ? "Or one-click fixture" : "One-click fixture"}
              </span>
              {fixtures.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  disabled={running || loopBusy}
                  onClick={() => {
                    setFixture(f.id);
                    void runScan({ address: "", fixture: f.id });
                  }}
                  className={`rounded-md border px-2.5 py-1 text-[11px] transition-colors disabled:opacity-50 ${
                    fixture === f.id
                      ? "border-gold/60 text-gold bg-gold/10"
                      : "border-brand-700 text-brand-300 hover:border-gold/40 hover:text-brand-100"
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          )}
          <p className="mt-3 text-[11px] text-brand-500 leading-relaxed">
            Lane A only: S0–S6 cheap skim + gate. A fixture overrides the address field.
            Continuous mode samples a contract that emitted a Transfer in one recent block, keeps it when Etherscan has verified source, then waits before the next one.{" "}
            {liveIngest
              ? "Address runs fetch verified source live."
              : "Address-only runs have no bytecode without an Etherscan key, so they land in manual-review by design — use a fixture for a real pass."}{" "}
            Receipts download as Markdown.
          </p>
        </form>

        {(running || loopBusy || phase === "wait") && (
          <div
            role="status"
            className="mt-4 text-xs text-gold/90 border border-gold/30 rounded-lg px-3 py-2 bg-gold/5 flex items-center gap-3"
          >
            <span className="inline-block h-2 w-2 rounded-full bg-gold animate-pulse" aria-hidden />
            <span className="flex-1">
              {loopState === "stopping" ? (
                running
                  ? `Stopping after this scan. ${loopCount} scanned this session.`
                  : `Stopping. ${loopCount} scanned this session. No further scan will start.`
              ) : phase === "wait" ? (
                `Next scan in ${waitLeft ?? gapSec}s. ${loopCount} scanned this session. Waiting so the free-tier key stays under 3 calls per second.`
              ) : phase === "sample" ? (
                `Choosing the next verified contract. ${loopCount} scanned this session.`
              ) : (
                <>
                  Lane A{dryRun ? " dry-run" : ""} on{" "}
                  {fixture ? `fixture ${fixtures.find((f) => f.id === fixture)?.label ?? fixture}` : address || "—"}
                  {loopBusy && randomPick?.contract_name ? ` (${randomPick.contract_name})` : ""}
                  {loopBusy ? ` · ${loopCount} scanned this session` : ""}
                  {" · "}ingest → IR → S0–S6
                  {fixture
                    ? " · fixtures usually finish in about a second"
                    : liveIngest
                      ? " · live Etherscan ingest can take a minute or two"
                      : " · stub ingest (no key)"}
                </>
              )}
            </span>
            {phase !== "wait" && <span className="tabular-nums text-gold/70">{elapsed}s</span>}
          </div>
        )}
        {loopMessage && !running && (
          <p className={`mt-4 text-sm rounded-lg px-3 py-2 border ${
            loopState === "paused"
              ? "text-amber-200 border-amber-900/60 bg-amber-950/20"
              : "text-brand-300 border-brand-800 bg-brand-900/40"
          }`}>
            {loopMessage}
            {loopCount > 0 ? ` ${loopCount} scanned this session.` : ""}
          </p>
        )}
        {runError && (
          <p className="mt-4 text-sm text-rose-300 border border-rose-900/60 rounded-lg px-3 py-2 bg-rose-950/20">
            {runError}
            {/python|runtime|unavailable|not importable/i.test(runError) &&
              " — the scanner's Python runtime isn't available on this host. Run it locally: npm run dev, or the eth-scanner CLI."}
          </p>
        )}
        {lastRun?.ok && lastRun.result && (
          <div className="mt-4 rounded-lg border border-brand-700/80 bg-brand-900/50 px-4 py-3 text-xs">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-[10px] tracking-[0.14em] uppercase text-gold/80 font-semibold">
                Last run · Lane A{lastRun.dry_run ? " · dry-run" : ""}
                {lastRun.fixture ? ` · fixture ${lastRun.fixture}` : ""}
                {randomPick?.address && lastRun.result.address.toLowerCase() === randomPick.address.toLowerCase()
                  ? " · random contract"
                  : ""}
                {fmtMs(lastRun.duration_ms) ? ` · ${fmtMs(lastRun.duration_ms)}` : ""}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <ReceiptLink
                  markdown={lastRun.receipt_markdown}
                  filename={lastRun.receipt_filename}
                  url={lastRun.receipt_url}
                />
              </div>
            </div>
            <p className="mt-2 font-mono text-[11px] text-brand-200">
              {lastRun.result.address}
              {lastRun.fixture && (
                <span className="ml-2 font-sans text-brand-500">placeholder address for a local fixture</span>
              )}
            </p>
            {lastRun.result.bucket && BUCKET_META[lastRun.result.bucket as Bucket] && (
              <p className={`mt-2 inline-block rounded-md border px-2 py-0.5 text-[10px] tracking-[0.12em] uppercase ${BUCKET_META[lastRun.result.bucket as Bucket].cls}`}>
                {BUCKET_META[lastRun.result.bucket as Bucket].label} · {BUCKET_META[lastRun.result.bucket as Bucket].hint}
              </p>
            )}
            <p className="mt-2 text-brand-200">
              Bucket <span className="text-brand-50">{lastRun.result.bucket ?? "—"}</span>
              {" · "}heat {lastRun.result.heat ?? 0}
              <span className="text-brand-500"> (evidence only)</span>
              {" · "}src/IR {lastRun.result.src_confidence ?? "—"} / {lastRun.result.ir_confidence ?? "—"}
              {lastRun.result.scope ? ` · scope ${lastRun.result.scope}` : ""}
              {lastRun.result.contract_class ? ` · ${lastRun.result.contract_class}` : ""}
              {lastRun.result.known_safe ? " · known-safe" : ""}
            </p>
            {lastRun.result.dropped && (
              <p className="mt-1 text-brand-400">
                Dropped{lastRun.result.drop_reason ? ` — ${lastRun.result.drop_reason}` : ""}
              </p>
            )}
            {lastRun.result.dropped &&
              lastRun.result.drop_reason === "empty EOA / zero-code" &&
              !lastRun.live_ingest && (
                <p className="mt-2 text-amber-200/90 leading-relaxed">
                  Not a confirmed EOA. ETHERSCAN_API_KEYS is unset, so Lane A had no bytecode.
                  Pick a local fixture or set keys for live ingest.
                </p>
              )}
            {(lastRun.result.funds_usd != null || lastRun.result.funds_status) && (
              <div className="mt-2 text-brand-300">
                <p>
                  Funds{" "}
                  <span className="text-brand-100 font-mono">
                    {lastRun.result.funds_usd != null
                      ? `$${Number(lastRun.result.funds_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
                      : "—"}
                  </span>
                  {lastRun.result.funds_status ? ` · ${lastRun.result.funds_status}` : ""}
                </p>
                {(lastRun.result.funds_breakdown?.length ?? 0) > 0 && (
                  <ul className="mt-1 text-[11px] text-brand-400 list-disc pl-4 space-y-0.5">
                    {lastRun.result.funds_breakdown!.slice(0, 8).map((a, i) => (
                      <li key={`${a.symbol}-${i}`}>
                        {a.symbol}
                        {a.kind ? ` (${a.kind})` : ""}
                        {a.usd != null ? ` · $${Number(a.usd).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {lastRun.result.value_movers?.length > 0 && (
              <p className="mt-2 text-brand-300">
                Value movers:{" "}
                <span className="font-mono text-[11px] text-brand-100">{lastRun.result.value_movers.join(", ")}</span>
              </p>
            )}
            {((lastRun.result.engine_leads?.length ?? 0) > 0 ||
              (lastRun.result.confirmed_findings?.length ?? 0) > 0) && (
              <div className="mt-3 space-y-2 border-t border-brand-800/60 pt-3">
                <p className="text-[10px] tracking-[0.14em] uppercase text-brand-500">
                  Engine leads vs confirmed
                  {lastRun.result.engine_timing?.total_ms != null
                    ? ` · ${fmtMs(Number(lastRun.result.engine_timing.total_ms))} engines`
                    : ""}
                </p>
                {(lastRun.result.confirmed_findings ?? [])
                  .filter((c) => c && c.confirmed)
                  .map((c, i) => (
                    <div key={`cf-${i}`} className="rounded-md border border-emerald-800/50 bg-emerald-950/20 px-2 py-1.5">
                      <p className="text-[11px] text-emerald-200">
                        Confirmed · {String(c.lead_id ?? "lead")}
                        <span className="ml-2 text-brand-500">
                          by {String(c.method ?? "eth_call")}
                          {["fuzz", "symbolic"].includes(String(c.method))
                            ? " · proof of a bug, not an attack"
                            : ""}
                        </span>
                      </p>
                      <p className="mt-0.5 font-mono text-[10px] text-brand-300 break-all">
                        {String(c.evidence ?? "").slice(0, 280)}
                      </p>
                    </div>
                  ))}
                {(lastRun.result.engine_timing &&
                  (lastRun.result.engine_timing.oracle_ms != null ||
                    lastRun.result.engine_timing.admin_ms != null ||
                    lastRun.result.engine_timing.halmos_ms != null)) && (
                  <p className="text-[10px] text-brand-500">
                    stages
                    {lastRun.result.engine_timing.ran_oracle
                      ? ` · oracle conf ${Number(lastRun.result.engine_timing.oracle_confirmed ?? 0)}`
                      : ""}
                    {lastRun.result.engine_timing.ran_admin
                      ? ` · admin conf ${Number(lastRun.result.engine_timing.admin_confirmed ?? 0)}`
                      : ""}
                    {lastRun.result.engine_timing.ran_storage
                      ? ` · storage conf ${Number(lastRun.result.engine_timing.storage_confirmed ?? 0)}`
                      : ""}
                    {lastRun.result.engine_timing.ran_halmos
                      ? ` · halmos fail ${Number(lastRun.result.engine_timing.halmos_failures ?? 0)}`
                      : ""}
                    {lastRun.result.engine_timing.clone_leads != null
                      ? ` · clone leads ${Number(lastRun.result.engine_timing.clone_leads ?? 0)}`
                      : ""}
                  </p>
                )}
                {(lastRun.result.engine_leads ?? []).slice(0, 12).map((lead, i) => (
                  <div key={`el-${i}`} className="rounded-md border border-amber-900/40 bg-amber-950/10 px-2 py-1.5">
                    <p className="text-[11px] text-amber-200/90">
                      Lead · {String(lead.engine ?? "engine")}:{String(lead.rule ?? lead.id ?? "—")}
                      <span className="ml-2 text-brand-500">not heat until confirmed</span>
                    </p>
                    <p className="mt-0.5 font-mono text-[10px] text-brand-400 break-all">
                      {String(lead.title ?? lead.evidence ?? "").slice(0, 220)}
                    </p>
                  </div>
                ))}
              </div>
            )}
            {randomPick?.address && lastRun.result.address.toLowerCase() === randomPick.address.toLowerCase() && (
              <p className="mt-2 text-brand-300">
                {randomPick.contract_name || "Verified contract"}
                {randomPick.compiler ? ` · ${randomPick.compiler}` : ""}
                {randomPick.block_number != null ? ` · Transfer logs in block ${randomPick.block_number}` : ""}
              </p>
            )}
            {lastRun.result.notes.length > 0 && (
              <ul className="mt-2 text-brand-400 leading-relaxed list-disc pl-4 space-y-0.5">
                {lastRun.result.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            )}
            {lastRun.persist && (
              <p className="mt-2 text-[11px] text-brand-500">
                {lastRun.persist.ok
                  ? `Saved detailed run to Supabase (${lastRun.persist.run_id?.slice(0, 8)}…).`
                  : lastRun.persist.skipped
                    ? "Detailed Supabase persist skipped (credentials unset)."
                    : `Detailed Supabase persist soft-failed: ${lastRun.persist.error || "unknown"} (desk still works).`}
              </p>
            )}
            {randomPick?.note && lastRun.result.address.toLowerCase() === randomPick.address?.toLowerCase() && (
              <p className="mt-2 text-brand-500 leading-relaxed">{randomPick.note}</p>
            )}
          </div>
        )}

        {loopHistory.length > 0 && (
          <div className="mt-4 rounded-lg border border-brand-800/80 bg-brand-900/20 px-4 py-3">
            <p className="text-[10px] tracking-[0.14em] uppercase text-brand-500">
              Latest {loopHistory.length} of {loopCount} continuous scans
            </p>
            <ul className="mt-2 max-h-56 overflow-y-auto divide-y divide-brand-800/70">
              {loopHistory.map((row) => (
                <li key={row.key} className="py-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[11px]">
                  <span className="text-brand-200">{row.contract_name || "Contract"}</span>
                  <span className="font-mono text-brand-400">{row.address}</span>
                  <span className="text-brand-500">{row.bucket || "—"}{row.heat != null ? ` · heat ${row.heat}` : ""}</span>
                  <span className="text-brand-400 tabular-nums">
                    {row.funds_usd != null
                      ? `$${Number(row.funds_usd).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                      : row.funds_status || "funds —"}
                  </span>
                  {row.dropped && row.drop_reason ? (
                    <span className="text-amber-500/90 truncate max-w-[28rem]" title={row.drop_reason}>
                      {row.drop_reason}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-8 grid grid-cols-2 sm:grid-cols-5 gap-2">
          {(Object.keys(BUCKET_META) as Bucket[]).map((b) => {
            const meta = BUCKET_META[b];
            const n = counts[b] ?? 0;
            const active = bucket === b;
            return (
              <button
                key={b}
                type="button"
                onClick={() => setBucket(active ? "all" : b)}
                className={`text-left rounded-lg border px-3 py-3 transition-colors ${meta.cls} ${
                  active ? "bg-brand-800/70" : "bg-brand-900/40 hover:bg-brand-900"
                }`}
              >
                <div className="text-[10px] tracking-[0.14em] uppercase opacity-70">{meta.label}</div>
                <div className="text-2xl font-semibold tabular-nums mt-1">{n}</div>
              </button>
            );
          })}
        </div>

        {(feed?.precision || feed?.benchmark) && (
          <div className="mt-4 rounded-lg border border-brand-800/80 bg-brand-900/20 px-4 py-3 text-[11px] text-brand-300 space-y-2">
            {feed?.precision && (
              <div>
                <p className="text-[10px] tracking-[0.14em] uppercase text-brand-500">Triage precision</p>
                <p className="mt-1 tabular-nums text-brand-100">
                  flags {feed.precision.flagged ?? 0}
                  {" · "}true {feed.precision.confirmed_true ?? 0}
                  {" · "}false {feed.precision.confirmed_false ?? 0}
                  {" · "}open {feed.precision.open_flags ?? 0}
                  {feed.precision.precision != null
                    ? ` · precision ${(Number(feed.precision.precision) * 100).toFixed(1)}%`
                    : " · precision —"}
                </p>
              </div>
            )}
            {feed?.benchmark && (
              <div>
                <p className="text-[10px] tracking-[0.14em] uppercase text-brand-500">Labeled benchmark</p>
                <p className="mt-1 tabular-nums text-brand-100">
                  n {feed.benchmark.labeled ?? 0}
                  {" · "}FP {feed.benchmark.false_positive ?? 0}
                  {" · "}TN {feed.benchmark.true_negative ?? 0}
                  {feed.benchmark.false_positive_rate != null
                    ? ` · FPR ${(Number(feed.benchmark.false_positive_rate) * 100).toFixed(1)}%`
                    : ""}
                  {feed.benchmark.precision != null
                    ? ` · precision ${(Number(feed.benchmark.precision) * 100).toFixed(1)}%`
                    : " · precision —"}
                  {feed.benchmark.recall != null
                    ? ` · recall ${(Number(feed.benchmark.recall) * 100).toFixed(1)}%`
                    : ""}
                  {" · "}
                  {feed.benchmark.passes_baseline ? "baseline ok" : "baseline FAIL"}
                </p>
              </div>
            )}
            {!!feed?.alerts?.length && (
              <div>
                <p className="text-[10px] tracking-[0.14em] uppercase text-brand-500">Monitor alerts</p>
                <ul className="mt-1 space-y-1 text-brand-100">
                  {feed.alerts.slice(0, 5).map((a) => (
                    <li key={a.id || `${a.address}-${a.kind}-${a.detail}`} className="truncate">
                      <span className="text-brand-400">{a.kind}</span>{" "}
                      <span className="font-mono text-[10px]">{a.address.slice(0, 10)}…</span>{" "}
                      {a.detail}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div className="mt-6 flex flex-col sm:flex-row gap-3 sm:items-center">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter address / hash / confidence"
            className={`flex-1 ${inputCls}`}
          />
          <button type="button" onClick={() => void load()} disabled={running} className={btnSecondary}>
            Refresh
          </button>
          {session.length > 0 && useSession && (
            <button type="button" onClick={() => setSession([])} disabled={running} className={btnSecondary}>
              Clear session
            </button>
          )}
        </div>
        {useSession && session.length > 0 && (
          <p className="mt-2 text-[11px] text-brand-500">
            Session queue: runs from this tab, kept in your browser
            {feed?.ephemeral_store ? " (serverless dry-run storage isn't shared across requests)" : ""}. Receipts
            download from the run itself.
          </p>
        )}

        <div className="mt-6 overflow-x-auto border border-brand-800/80 rounded-lg">
          <table className="w-full text-left text-xs">
            <thead className="bg-brand-900/80 text-brand-400 tracking-[0.12em] uppercase">
              <tr>
                <th className="px-3 py-2 font-medium">Address</th>
                <th className="px-3 py-2 font-medium">Bucket</th>
                <th className="px-3 py-2 font-medium">Heat</th>
                <th className="px-3 py-2 font-medium">Src / IR</th>
                <th className="px-3 py-2 font-medium">TVL</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Receipt</th>
              </tr>
            </thead>
            <tbody>
              {shown.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-10 text-center text-brand-500">
                    {!feed && !error ? (
                      "Loading queue…"
                    ) : bucket !== "all" || q.trim() ? (
                      <>
                        Nothing matches this filter.{" "}
                        <button
                          type="button"
                          onClick={() => {
                            setBucket("all");
                            setQ("");
                          }}
                          className="text-gold hover:text-gold/80 underline-offset-2 hover:underline"
                        >
                          Show all
                        </button>
                      </>
                    ) : (
                      <>
                        <span className="block text-brand-300 mb-2">Queue is empty.</span>
                        Enter an address and click <span className="text-gold">Run</span>, or{" "}
                        <button
                          type="button"
                          disabled={running}
                          onClick={() => {
                            setFixture("gated_vault");
                            void runScan({ address: DEMO_ADDRESS, fixture: "gated_vault" });
                          }}
                          className="text-gold hover:text-gold/80 underline-offset-2 hover:underline disabled:opacity-50"
                        >
                          run the gated-vault fixture
                        </button>{" "}
                        to see a full Lane A pass.
                      </>
                    )}
                  </td>
                </tr>
              )}
              {shown.map((t) => {
                const srow = "key" in t ? (t as SessionRow) : null;
                const rowKey = srow?.key ?? t.address.toLowerCase();
                const active = selected === rowKey || selected === t.address.toLowerCase();
                const fxLabel = srow?.fixture ? fixtures.find((f) => f.id === srow.fixture)?.label ?? srow.fixture : null;
                return (
                  <tr
                    key={rowKey}
                    onClick={() => {
                      if (srow?.fixture) {
                        setFixture(srow.fixture);
                        setSelected(rowKey);
                        setRunError(null);
                      } else selectTarget(t.address);
                    }}
                    title={srow?.fixture ? "Select this fixture (Run to re-scan)" : "Select this address (Run to re-scan)"}
                    className={`border-t border-brand-800/70 cursor-pointer ${
                      active ? "bg-gold/10" : "hover:bg-brand-900/40"
                    }`}
                  >
                    <td className="px-3 py-2 font-mono text-[11px] text-brand-200">
                      {fxLabel ? (
                        <span className="font-sans text-brand-100">
                          {fxLabel} <span className="text-brand-500 text-[10px] uppercase tracking-wider">fixture</span>
                        </span>
                      ) : (
                        t.address
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {t.bucket && BUCKET_META[t.bucket] ? (
                        <span className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${BUCKET_META[t.bucket].cls}`}>
                          {BUCKET_META[t.bucket].label}
                        </span>
                      ) : (
                        <span className="text-brand-100">{t.bucket ?? "—"}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 tabular-nums">{t.heat ?? 0}</td>
                    <td className="px-3 py-2">
                      {t.src_confidence ?? "—"} / {t.ir_confidence ?? "—"}
                    </td>
                    <td className="px-3 py-2 tabular-nums" title={Array.isArray(t.funds_breakdown) ? t.funds_breakdown.map((a) => `${a.symbol}: $${a.usd ?? 0}`).join(" · ") : undefined}>
                      {t.funds_usd ?? t.tvl_usd ?? "—"}
                      {t.funds_status ? <span className="block text-[10px] text-brand-500">{t.funds_status}</span> : null}
                    </td>
                    <td className="px-3 py-2 text-brand-400">{t.status ?? "—"}</td>
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <ReceiptLink
                        markdown={srow?.receipt_markdown}
                        filename={srow?.receipt_filename}
                        url={srow?.fixture ? null : `/api/test/receipt?address=${encodeURIComponent(t.address)}`}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {(feed?.history?.runs?.length ?? 0) > 0 && (
          <div className="mt-10">
            <h2 className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold mb-3">
              Supabase history · last {feed!.history!.runs.length} detailed runs
            </h2>
            {feed?.history?.error && (
              <p className="mb-2 text-[11px] text-amber-200">{feed.history.error}</p>
            )}
            <div className="overflow-x-auto border border-brand-800/80 rounded-lg">
              <table className="w-full text-left text-xs">
                <thead className="bg-brand-900/80 text-brand-400 tracking-[0.12em] uppercase">
                  <tr>
                    <th className="px-3 py-2 font-medium">When</th>
                    <th className="px-3 py-2 font-medium">Kind</th>
                    <th className="px-3 py-2 font-medium">Address / fixture</th>
                    <th className="px-3 py-2 font-medium">Bucket / status</th>
                    <th className="px-3 py-2 font-medium">Findings</th>
                    <th className="px-3 py-2 font-medium">TVL / risk</th>
                  </tr>
                </thead>
                <tbody>
                  {feed!.history!.runs.map((r) => (
                    <tr key={r.id} className="border-t border-brand-800/60">
                      <td className="px-3 py-2 text-brand-400 whitespace-nowrap">
                        {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}
                      </td>
                      <td className="px-3 py-2 text-brand-200">{r.kind}</td>
                      <td className="px-3 py-2 font-mono text-[11px] text-brand-100">
                        {r.address || r.fixture || "—"}
                      </td>
                      <td className="px-3 py-2 text-brand-300">
                        {r.bucket || r.status || "—"}
                        {r.heat != null ? ` · heat ${r.heat}` : ""}
                      </td>
                      <td className="px-3 py-2 tabular-nums">{r.findings_count ?? 0}</td>
                      <td className="px-3 py-2 tabular-nums text-brand-400">
                        {r.money_at_risk_usd ?? r.tvl_usd ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <p className="mt-8 text-[11px] text-brand-600 leading-relaxed max-w-2xl">
          Buckets are ranking outputs from §6.0, not disclosure.{" "}
          {bucket !== "all" ? BUCKET_META[bucket].hint + " " : ""}
          Download receipt is Markdown only — paste into another AI as the full scan context.
          See <code className="text-brand-400">eth-scanner/README.md</code> and{" "}
          <code className="text-brand-400">docs/ETH_SWEEP_SCANNING_REFERENCE.md</code>.
        </p>
        </>
        )}

        {tab === "research" && <ResearchPanel
          fixtures={researchFeed?.fixtures ?? [
            { id: "erc4626_vault", label: "ERC-4626 vault" },
            { id: "yearn_v2", label: "Yearn V2-like" },
          ]}
          address={researchAddress}
          setAddress={setResearchAddress}
          fixture={researchFixture}
          setFixture={setResearchFixture}
          running={researchRunning}
          error={researchError}
          last={lastResearch}
          feed={researchFeed}
          uploaded={uploadedReceipt}
          setUploaded={setUploadedReceipt}
          onRun={() => void runResearch()}
          onRefresh={() => void loadResearch()}
        />}
        {tab === "engines" && <EnginesPanel />}
      </div>
    </main>
  );
}

function ReceiptLink({
  markdown,
  filename,
  url,
}: {
  markdown?: string | null;
  filename?: string | null;
  url?: string | null;
}) {
  const cls = "text-[11px] tracking-[0.08em] uppercase font-semibold text-gold hover:text-gold/80";
  if (markdown) {
    return (
      <button type="button" className={cls} onClick={() => downloadMarkdown(markdown, filename || "receipt.md")}>
        Download .md
      </button>
    );
  }
  if (url) {
    return (
      <a href={url} className={cls}>
        Download .md
      </a>
    );
  }
  return <span className="text-brand-600 text-[11px]">—</span>;
}

/** Compact mode banner: what's live, what's offline, and what that means for a run. */
function DeskStatus({ feed }: { feed: Feed | null }) {
  if (!feed) {
    return <p className="mt-4 text-[11px] text-brand-500">Checking desk capabilities…</p>;
  }
  const dry = feed.dry_run;
  const live = Boolean(feed.live_ingest);
  const offline = !live;
  const chip = (on: boolean) =>
    `rounded-md border px-2 py-1 ${on ? "border-emerald-800 text-emerald-200" : "border-amber-800/80 text-amber-200"}`;
  return (
    <div className="mt-4">
      <div className="flex flex-wrap gap-2 text-[10px] tracking-[0.12em] uppercase">
        <span className={chip(!dry)}>Persist · {dry ? "dry-run" : "live Supabase"}</span>
        <span className={chip(live)}>Ingest · {live ? "Etherscan live" : "offline (fixtures)"}</span>
      </div>
      <div
        className={`mt-3 rounded-lg border px-3 py-2.5 text-xs leading-relaxed ${
          offline ? "border-amber-800/50 bg-amber-950/10 text-brand-300" : "border-brand-800/80 bg-brand-900/50 text-brand-400"
        }`}
      >
        {offline ? (
          <>
            <span className="text-amber-200 font-semibold">Offline desk.</span> No Etherscan key on this
            deployment, so address scans have no verified source and land in{" "}
            <span className="text-rose-200">manual-review</span> on purpose (a missing input is never a silent
            no). Local fixtures run the full S0–S6 path on real Solidity — pick one below.
          </>
        ) : (
          <>
            <span className="text-emerald-200 font-semibold">Live ingest.</span> Address scans fetch verified
            source and bytecode from Etherscan.
          </>
        )}{" "}
        {dry
          ? "Legacy eth_scan_* queue is dry-run; detailed test_scan_* rows still soft-fail persist when a service/secret key is present."
          : "Results persist to Supabase (eth_scan_* queue + detailed test_scan_* runs/findings/triage)."}
        {feed.note && (
          <details className="mt-1.5 text-[11px] text-brand-500">
            <summary className="cursor-pointer select-none hover:text-brand-300">Details</summary>
            <p className="mt-1">{feed.note}</p>
          </details>
        )}
      </div>
    </div>
  );
}

function ResearchPanel({
  fixtures,
  address,
  setAddress,
  fixture,
  setFixture,
  running,
  error,
  last,
  feed,
  uploaded,
  setUploaded,
  onRun,
  onRefresh,
}: {
  fixtures: FixtureOpt[];
  address: string;
  setAddress: (v: string) => void;
  fixture: string;
  setFixture: (v: string) => void;
  running: boolean;
  error: string | null;
  last: ResearchResponse | null;
  feed: ResearchFeed | null;
  uploaded: ResearchResult | null;
  setUploaded: (v: ResearchResult | null) => void;
  onRun: () => void;
  onRefresh: () => void;
}) {
  const shown = last?.result || uploaded;
  const latest = feed?.latest;
  const pythonMissing = Boolean(error && /python|unavailable|not importable/i.test(error));
  const elapsed = useElapsed(running);
  const [uploadError, setUploadError] = useState<string | null>(null);

  return (
    <div className="mt-8">
      <p className="text-sm text-brand-400 leading-relaxed max-w-2xl">
        Defensive research stack (L0–L5). Findings are invariant / property / detector
        rows with <span className="text-brand-200">defensive_only=true</span>. Optional
        forge / echidna / slither / halmos / hevm skip when missing. Lane A remains the gate.
      </p>
      {pythonMissing && (
        <p className="mt-3 text-xs text-amber-200/90 border border-amber-800/70 rounded-lg px-3 py-2">
          Live research run needs a local Python runtime. Show the last receipt or upload a
          previously downloaded research JSON — no keys are invented.
        </p>
      )}

      <form
        className="mt-6 rounded-lg border border-brand-800/80 bg-brand-900/30 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          onRun();
        }}
      >
        <div className="flex flex-col sm:flex-row gap-3 sm:items-end">
          <label className="flex-1 min-w-0">
            <span className="block text-[10px] tracking-[0.14em] uppercase text-brand-500 mb-1.5">
              Address
            </span>
            <input
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="0x… or use a fixture"
              spellCheck={false}
              autoComplete="off"
              className={`w-full font-mono text-[13px] ${inputCls}`}
            />
          </label>
          <label className="sm:w-56">
            <span className="block text-[10px] tracking-[0.14em] uppercase text-brand-500 mb-1.5">
              Research fixture
            </span>
            <select
              value={fixture}
              onChange={(e) => setFixture(e.target.value)}
              className={`w-full ${inputCls}`}
            >
              <option value="">None — address only</option>
              {fixtures.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={running} className={btnPrimary} aria-busy={running}>
            {running ? "Running…" : "Run dry-run"}
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button type="button" onClick={onRefresh} disabled={running} className={btnSecondary}>
            Show last receipt
          </button>
          <label className="text-[11px] text-brand-400">
            <span className="mr-2 uppercase tracking-[0.12em] text-brand-500">Upload receipt</span>
            <input
              type="file"
              accept=".json,application/json"
              className="text-[11px] text-brand-300"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                setUploadError(null);
                const reader = new FileReader();
                reader.onload = () => {
                  try {
                    const parsed = JSON.parse(String(reader.result || "")) as Record<string, unknown>;
                    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || (!parsed.address && !Array.isArray(parsed.findings))) {
                      throw new Error("not a research receipt");
                    }
                    const findings = Array.isArray(parsed.findings) ? parsed.findings : [];
                    setUploaded({
                      address: String(parsed.address || ""),
                      gated: Boolean(parsed.gated),
                      gate_reason: String(parsed.gate_reason || ""),
                      role: parsed.role == null ? null : String(parsed.role),
                      scope: parsed.scope == null ? null : String(parsed.scope),
                      layers_run: Array.isArray(parsed.layers_run) ? parsed.layers_run.map(String) : [],
                      layers_skipped: Array.isArray(parsed.layers_skipped)
                        ? parsed.layers_skipped.map((s) => {
                            const row = (s || {}) as { layer?: string; reason?: string };
                            return { layer: String(row.layer || ""), reason: String(row.reason || "") };
                          })
                        : [],
                      findings: findings.map((f) => {
                        const row = (f || {}) as ResearchFinding;
                        return {
                          id: String(row.id || ""),
                          severity: String(row.severity || "info"),
                          layer: String(row.layer || ""),
                          title: String(row.title || ""),
                          evidence: String(row.evidence || ""),
                          address: String(row.address || ""),
                          detector: String(row.detector || ""),
                          defensive_only: true,
                        };
                      }),
                      notes: Array.isArray(parsed.notes) ? parsed.notes.map(String) : [],
                      receipt_md_path: parsed.receipt_md_path == null ? null : String(parsed.receipt_md_path),
                      receipt_json_path: parsed.receipt_json_path == null ? null : String(parsed.receipt_json_path),
                      defensive_only: true,
                    });
                  } catch {
                    setUploaded(null);
                    setUploadError(`${file.name} isn't a research receipt JSON (expected address + findings).`);
                  }
                };
                reader.readAsText(file);
              }}
            />
          </label>
        </div>
        <p className="mt-3 text-[11px] text-brand-500 leading-relaxed">
          Dry-run only. Writes <code className="text-brand-300">eth-scanner/work/receipts/research-*.md</code>.
          Does not replace Lane A buckets.
        </p>
      </form>

      {running && (
        <div
          role="status"
          className="mt-4 text-xs text-gold/90 border border-gold/30 rounded-lg px-3 py-2 bg-gold/5 flex items-center gap-3"
        >
          <span className="inline-block h-2 w-2 rounded-full bg-gold animate-pulse" aria-hidden />
          <span className="flex-1">
            Research dry-run{fixture ? ` on fixture ${fixture}` : address ? ` on ${address}` : ""} · Lane A gate → IR →
            L2/L3 → fuzz/symbolic (missing tools are skipped and listed)
          </span>
          <span className="tabular-nums text-gold/70">{elapsed}s</span>
        </div>
      )}
      {error && <p className="mt-4 text-sm text-rose-300">{error}</p>}
      {uploadError && <p className="mt-4 text-sm text-rose-300">{uploadError}</p>}
      {!running && !shown && !latest && !error && (
        <p className="mt-4 text-xs text-brand-500 border border-dashed border-brand-800 rounded-lg px-3 py-6 text-center">
          No research receipt yet. Run a fixture dry-run above, or upload a research JSON you downloaded earlier.
        </p>
      )}

      {(shown || latest) && (
        <ResearchSummary
          result={shown}
          latest={shown ? null : latest}
          receiptUrl={last?.receipt_url || latest?.receipt_url || null}
          receiptMarkdown={shown === last?.result ? last?.receipt_markdown ?? null : null}
          receiptFilename={shown === last?.result ? last?.receipt_filename ?? null : null}
          durationMs={shown === last?.result ? last?.duration_ms : undefined}
          fixture={last?.fixture}
        />
      )}
      {last?.persist && (
        <p className="mt-3 text-[11px] text-brand-500">
          {last.persist.ok
            ? `Saved detailed research run to Supabase (${last.persist.run_id?.slice(0, 8)}… · ${last.persist.findings_count ?? 0} findings).`
            : last.persist.skipped
              ? "Detailed Supabase persist skipped (credentials unset)."
              : `Detailed Supabase persist soft-failed: ${last.persist.error || "unknown"} (desk still works).`}
        </p>
      )}

      <p className="mt-8 text-[11px] text-brand-600 leading-relaxed max-w-2xl">
        Research findings are defensive reports, not disclosure. See{" "}
        <code className="text-brand-400">eth-scanner/research/README.md</code>.
      </p>
    </div>
  );
}

function ResearchSummary({
  result,
  latest,
  receiptUrl,
  receiptMarkdown,
  receiptFilename,
  durationMs,
  fixture,
}: {
  result: ResearchResult | null;
  latest: ResearchFeed["latest"] | null | undefined;
  receiptUrl: string | null;
  receiptMarkdown?: string | null;
  receiptFilename?: string | null;
  durationMs?: number;
  fixture?: string | null;
}) {
  const address = result?.address || latest?.address || "";
  const gated = result?.gated ?? latest?.gated ?? false;
  const gate = result?.gate_reason || latest?.gate_reason || "";
  const role = result?.role || latest?.role;
  const scope = result?.scope || latest?.scope;
  const layers = result?.layers_run || latest?.layers_run || [];
  const skips = result?.layers_skipped || latest?.layers_skipped || [];
  const findings = [...(result?.findings || latest?.findings || [])].sort(
    (a, b) => (SEV_RANK[a.severity] ?? 9) - (SEV_RANK[b.severity] ?? 9) || a.layer.localeCompare(b.layer),
  );
  const sevCounts = findings.reduce<Record<string, number>>((acc, f) => {
    acc[f.severity] = (acc[f.severity] ?? 0) + 1;
    return acc;
  }, {});
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="mt-4 rounded-lg border border-brand-700/80 bg-brand-900/50 px-4 py-3 text-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[10px] tracking-[0.14em] uppercase text-gold/80 font-semibold">
          Research receipt · dry-run
          {fixture ? ` · fixture ${fixture}` : ""}
          {latest?.stack_version ? ` · v${latest.stack_version}` : ""}
          {fmtMs(durationMs) ? ` · ${fmtMs(durationMs)}` : ""}
        </p>
        <ReceiptLink markdown={receiptMarkdown} filename={receiptFilename} url={receiptMarkdown ? null : receiptUrl} />
      </div>
      <p className="mt-2 font-mono text-[11px] text-brand-200">{address || "—"}</p>
      <p className="mt-2 text-brand-200">
        {gated ? "Gated at L1" : "Proceeded past L1"}
        {gate ? ` — ${gate}` : ""}
        {role ? ` · ${role}` : ""}
        {scope ? ` · ${scope}` : ""}
      </p>
      <p className="mt-2 text-brand-300">
        Layers ran: {layers.length ? layers.join(", ") : "—"}
      </p>
      {skips.length > 0 && (
        <details className="mt-2 text-brand-400">
          <summary className="cursor-pointer select-none hover:text-brand-200">
            {skips.length} layer step{skips.length === 1 ? "" : "s"} skipped (tools not on this host)
          </summary>
          <ul className="mt-1 space-y-1 pl-3">
            {skips.map((s, i) => (
              <li key={`${s.layer}-${i}`}>
                <span className="text-brand-300">{s.layer}</span> — {s.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
      {findings.length > 0 && (
        <p className="mt-3 flex flex-wrap gap-3 text-[10px] uppercase tracking-[0.12em]">
          {["critical", "high", "medium", "low", "info"].filter((k) => sevCounts[k]).map((k) => (
            <span key={k} className={SEV_CLS[k]}>
              {sevCounts[k]} {k}
            </span>
          ))}
        </p>
      )}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-left">
          <thead className="text-brand-400 tracking-[0.12em] uppercase">
            <tr>
              <th className="pr-3 py-1 font-medium">ID</th>
              <th className="pr-3 py-1 font-medium">Layer</th>
              <th className="pr-3 py-1 font-medium">Sev</th>
              <th className="pr-3 py-1 font-medium">Detector</th>
              <th className="py-1 font-medium">Title</th>
            </tr>
          </thead>
          <tbody>
            {findings.length === 0 && (
              <tr>
                <td colSpan={5} className="py-3 text-brand-500">
                  No findings in this receipt. That is not a verdict of safety.
                </td>
              </tr>
            )}
            {findings.map((f, i) => {
              const k = `${f.id}-${i}`;
              const isOpen = open === k;
              return (
                <tr
                  key={k}
                  className="border-t border-brand-800/70 align-top cursor-pointer hover:bg-brand-900/40"
                  onClick={() => setOpen(isOpen ? null : k)}
                  aria-expanded={isOpen}
                >
                  <td className="pr-3 py-1.5 font-mono text-[10px] text-brand-300">{f.id}</td>
                  <td className="pr-3 py-1.5">{f.layer}</td>
                  <td className={`pr-3 py-1.5 uppercase ${SEV_CLS[f.severity] ?? ""}`}>{f.severity}</td>
                  <td className="pr-3 py-1.5 text-brand-300">{f.detector || "—"}</td>
                  <td className="py-1.5 text-brand-100">
                    {f.title}
                    {f.evidence && (
                      <span className={`block mt-0.5 text-brand-400 ${isOpen ? "whitespace-pre-wrap" : "truncate max-w-[460px]"}`}>
                        {f.evidence}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
