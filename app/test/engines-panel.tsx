"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type EngineRow = {
  id: string;
  name: string;
  kind: string;
  target: string;
  fork: string;
  fork_url: string;
  upstream_url: string;
  envBin: string;
  install: string;
  blurb: string;
  status: "installed" | "missing" | "stub";
  binary: string | null;
  version: string | null;
  reason: string | null;
};

type Corpus = { id: string; name: string; fork: string; fork_url: string; upstream: string; blurb: string; classes: string[] };

type Catalog = {
  ok: boolean;
  on_vercel: boolean;
  running: boolean;
  engines: EngineRow[];
  corpora: Corpus[];
  classes: Record<string, string>;
  priors: Record<string, { pattern: string; rate: number; n: number }>;
  fixtures: string[];
  summary: { installed: number; stub: number; missing: number };
};

type Finding = {
  id: string;
  engine: string;
  rule: string;
  title: string;
  severity: string;
  confidence: string;
  class: string;
  location: { file?: string | null; line?: number | null; contract?: string | null; function?: string | null };
  evidence: string;
  references: { corpus: string; label: string; url: string }[];
  triage: number;
};

type PersistInfo = {
  ok: boolean;
  skipped?: boolean;
  error?: string;
  run_id?: string;
  findings_count?: number;
  finding_ids?: { finding_key: string; id: string }[];
};

type PasteResponse = {
  ok: boolean;
  error?: string;
  engine?: string;
  requested_engine?: string;
  detected?: boolean;
  warning?: string | null;
  findings?: Finding[];
  runs?: EngineRun[];
  duration_ms?: number;
  persist?: PersistInfo;
};

const TRIAGE_STATUSES = [
  "open",
  "reviewing",
  "confirmed",
  "dismissed",
  "false_positive",
  "human_yes",
  "human_no",
] as const;

type TriageStatus = (typeof TRIAGE_STATUSES)[number];

type EngineRun = {
  engine: string;
  status: string;
  reason: string | null;
  duration_ms: number;
  exit_code: number | null;
  findings_count: number;
  log_tail: string;
};

const STATUS_STYLE: Record<string, string> = {
  installed: "border-emerald-800 text-emerald-200",
  stub: "border-amber-800/80 text-amber-200",
  missing: "border-brand-700 text-brand-400",
};

const SEV_ORDER = ["critical", "high", "medium", "low", "info"] as const;
const SEV_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };

/** Paste hints per engine (what the normalizer expects). */
const PASTE_HINT: Record<string, string> = {
  slither: "slither . --json -   → paste the JSON",
  aderyn: "aderyn . -o report.json   → paste report.json",
  achecker: "achecker.py … output   → paste the text",
  echidna: "echidna … --config …   → paste the text output",
  medusa: "medusa fuzz   → paste the text output",
  ityfuzz: "ityfuzz evm …   → paste the text output",
  halmos: "halmos --function check_   → paste the [PASS]/[FAIL] output",
  mythril: "myth analyze <file> -o json   → paste the JSON",
};

/**
 * A small, illustrative Slither-shaped report so an offline desk can show the
 * full normalize → classify → triage → prior-art path. Detector descriptions
 * only — no exploit code, calldata or call sequences.
 */
const SAMPLE_SLITHER = JSON.stringify(
  {
    success: true,
    results: {
      detectors: [
        {
          check: "reentrancy-eth",
          impact: "High",
          confidence: "Medium",
          description: "Reentrancy in SampleVault.withdraw(uint256): external call before balance update (sample).",
          elements: [
            {
              type: "function",
              name: "withdraw",
              source_mapping: { filename_relative: "src/SampleVault.sol", lines: [48] },
              type_specific_fields: { parent: { name: "SampleVault" } },
            },
          ],
        },
        {
          check: "arbitrary-send-eth",
          impact: "High",
          confidence: "High",
          description: "SampleVault.sweep(address) sends eth to a caller-chosen destination without an owner check (sample).",
          elements: [
            {
              type: "function",
              name: "sweep",
              source_mapping: { filename_relative: "src/SampleVault.sol", lines: [71] },
              type_specific_fields: { parent: { name: "SampleVault" } },
            },
          ],
        },
        {
          check: "unchecked-transfer",
          impact: "Medium",
          confidence: "Medium",
          description: "SampleVault.deposit(uint256) ignores the return value of token.transferFrom (sample).",
          elements: [
            {
              type: "function",
              name: "deposit",
              source_mapping: { filename_relative: "src/SampleVault.sol", lines: [33] },
              type_specific_fields: { parent: { name: "SampleVault" } },
            },
          ],
        },
        {
          check: "naming-convention",
          impact: "Informational",
          confidence: "High",
          description: "Parameter SampleVault.withdraw(uint256)._amt is not in mixedCase (sample).",
          elements: [],
        },
      ],
    },
  },
  null,
  2,
);

function findingsMarkdown(list: Finding[], source: string): string {
  const lines = [
    `# Engine desk findings — ${source}`,
    "",
    `Generated ${new Date().toISOString()}. Leads, not verdicts. defensive_only=true.`,
    "",
    "| Triage | Severity | Conf. | Class | Engine · rule | Where | Evidence |",
    "|---:|---|---|---|---|---|---|",
  ];
  for (const f of list) {
    const where =
      [f.location.contract, f.location.function].filter(Boolean).join(".") +
      (f.location.file ? ` ${f.location.file}${f.location.line ? `:${f.location.line}` : ""}` : "");
    const cell = (v: string) => v.replace(/\|/g, "\\|").replace(/\n/g, " ");
    lines.push(
      `| ${f.triage} | ${f.severity} | ${f.confidence} | ${f.class} | ${cell(`${f.engine} · ${f.rule}`)} | ${cell(where.trim() || "—")} | ${cell(f.evidence)} |`,
    );
  }
  return lines.join("\n") + "\n";
}

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={(ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        void navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        });
      }}
      className="shrink-0 text-[10px] uppercase tracking-wider text-gold/80 hover:text-gold"
    >
      {done ? "Copied" : label}
    </button>
  );
}

const SEV_STYLE: Record<string, string> = {
  critical: "text-rose-200",
  high: "text-rose-300",
  medium: "text-amber-200",
  low: "text-brand-200",
  info: "text-brand-400",
};

export default function EnginesPanel() {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [fixture, setFixture] = useState("open_vault");
  const [running, setRunning] = useState<null | "run" | "paste">(null);
  const [runs, setRuns] = useState<EngineRun[] | null>(null);
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [meta, setMeta] = useState<{ source: string; warning?: string | null; duration_ms?: number } | null>(null);
  const [pasteEngine, setPasteEngine] = useState("slither");
  const [paste, setPaste] = useState("");
  const [classFilter, setClassFilter] = useState("all");
  const [sevFilter, setSevFilter] = useState("all");
  const [persistInfo, setPersistInfo] = useState<PersistInfo | null>(null);
  const [dbIds, setDbIds] = useState<Record<string, string>>({});
  const [triageStatus, setTriageStatus] = useState<Record<string, TriageStatus>>({});
  const [triageBusy, setTriageBusy] = useState<string | null>(null);
  const [triageErr, setTriageErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      const r = await fetch("/api/test/engines", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as Catalog;
      setCat(j);
      setPicked((prev) => (prev.size ? prev : new Set(j.engines.filter((e) => e.status === "installed").map((e) => e.id))));
      if (j.fixtures.length && !j.fixtures.includes(fixture)) setFixture(j.fixtures[0]);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : "failed to load engines");
    }
  }, [fixture]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function post(body: Record<string, unknown>, kind: "run" | "paste") {
    setRunning(kind);
    setErr(null);
    const t0 = performance.now();
    try {
      const r = await fetch("/api/test/engines", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = (await r.json().catch(() => ({ ok: false, error: `HTTP ${r.status}` }))) as PasteResponse;
      if (!j.ok) throw new Error(j.error || `HTTP ${r.status}`);
      setFindings(j.findings ?? []);
      setRuns(j.runs ?? null);
      setClassFilter("all");
      setSevFilter("all");
      setPersistInfo(j.persist ?? null);
      const ids: Record<string, string> = {};
      const statuses: Record<string, TriageStatus> = {};
      for (const row of j.persist?.finding_ids ?? []) {
        ids[row.finding_key] = row.id;
        statuses[row.finding_key] = "open";
      }
      setDbIds(ids);
      setTriageStatus(statuses);
      setTriageErr(null);
      setMeta({
        source:
          kind === "paste"
            ? `pasted ${j.engine ?? body.engine}${j.detected ? ` (auto-detected; you picked ${j.requested_engine})` : ""}`
            : `fixture ${String(body.fixture)}`,
        warning: j.warning ?? null,
        duration_ms: j.duration_ms ?? Math.round(performance.now() - t0),
      });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "request failed");
    } finally {
      setRunning(null);
    }
  }

  async function setFindingTriage(findingKey: string, to_status: TriageStatus) {
    const finding_id = dbIds[findingKey];
    if (!finding_id) return;
    setTriageBusy(findingKey);
    setTriageErr(null);
    try {
      const r = await fetch("/api/test/triage", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ finding_id, to_status, actor: "desk" }),
      });
      const j = (await r.json().catch(() => ({ ok: false, error: `HTTP ${r.status}` }))) as {
        ok: boolean;
        error?: string;
      };
      if (!j.ok) throw new Error(j.error || `HTTP ${r.status}`);
      setTriageStatus((prev) => ({ ...prev, [findingKey]: to_status }));
    } catch (e) {
      setTriageErr(e instanceof Error ? e.message : "triage update failed");
    } finally {
      setTriageBusy(null);
    }
  }

  const sorted = useMemo(
    () =>
      [...(findings ?? [])].sort(
        (a, b) => (SEV_RANK[a.severity] ?? 9) - (SEV_RANK[b.severity] ?? 9) || b.triage - a.triage,
      ),
    [findings],
  );
  const visible = useMemo(
    () =>
      sorted.filter(
        (f) => (classFilter === "all" || f.class === classFilter) && (sevFilter === "all" || f.severity === sevFilter),
      ),
    [sorted, classFilter, sevFilter],
  );
  const classesSeen = useMemo(() => Array.from(new Set(sorted.map((f) => f.class))).sort(), [sorted]);
  const sevCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of sorted) c[f.severity] = (c[f.severity] ?? 0) + 1;
    return c;
  }, [sorted]);

  const offline = cat ? cat.summary.installed === 0 : false;
  const busy = running !== null;

  const pasteBox = (
    <div className={`rounded-lg border p-4 ${offline ? "border-gold/40 bg-gold/5" : "border-brand-800/80 bg-brand-900/30"}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <h2 className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold">
          {offline ? "Step 2 · Paste engine output" : "Paste engine output"}
        </h2>
        <button
          type="button"
          onClick={() => {
            setPasteEngine("slither");
            setPaste(SAMPLE_SLITHER);
          }}
          className="text-[10px] uppercase tracking-wider text-gold/80 hover:text-gold"
        >
          Load sample Slither report
        </button>
      </div>
      <p className="text-xs text-brand-400 mb-3">
        Paste a report (Slither / Aderyn / Mythril JSON, or Echidna / Medusa / ityfuzz / Halmos / AChecker text). It
        is normalized into one schema, classified, triaged and cross-referenced. If the picked engine doesn&apos;t
        match, the desk auto-detects and tells you. 2 MB max; nothing is stored.
      </p>
      <div className="flex flex-wrap gap-3 items-start">
        <select
          aria-label="Engine that produced this output"
          className="rounded-md border border-brand-700 bg-brand-950 px-2 py-1.5 text-xs text-brand-100"
          value={pasteEngine}
          onChange={(e) => setPasteEngine(e.target.value)}
        >
          {(cat?.engines ?? [{ id: "slither", name: "Slither" } as EngineRow]).map((e) => (
            <option key={e.id} value={e.id}>
              {e.name}
            </option>
          ))}
        </select>
        <textarea
          aria-label="Engine output"
          className="flex-1 min-w-[240px] h-32 rounded-md border border-brand-700 bg-brand-950 p-2 font-mono text-[11px] text-brand-100"
          placeholder={PASTE_HINT[pasteEngine] ?? "paste engine output here"}
          value={paste}
          onChange={(e) => setPaste(e.target.value)}
        />
        <div className="flex flex-col gap-2">
          <button
            type="button"
            disabled={busy || !paste.trim()}
            onClick={() => void post({ engine: pasteEngine, output: paste }, "paste")}
            className="px-4 py-2 text-[11px] tracking-[0.15em] uppercase font-semibold rounded-md border border-gold/60 text-gold bg-gold/10 disabled:opacity-40"
          >
            {running === "paste" ? "Normalizing…" : "Normalize"}
          </button>
          {paste && (
            <button
              type="button"
              onClick={() => setPaste("")}
              className="text-[10px] uppercase tracking-wider text-brand-500 hover:text-brand-300"
            >
              Clear
            </button>
          )}
        </div>
      </div>
      <p className="mt-2 text-[10px] text-brand-600">{paste ? `${(paste.length / 1024).toFixed(1)} KB` : ""}</p>
    </div>
  );

  return (
    <section className="mt-8 space-y-8">
      <p className="text-sm text-brand-400 max-w-3xl leading-relaxed">
        One desk, eight engines, one finding schema. Static and symbolic engines read a local fixture; fuzzers and
        Halmos run the defensive conservation harness (<code className="text-brand-200">eth-scanner/research/fuzz</code>).
        Every finding is framed as <span className="text-gold">funds at risk</span> and cross-referenced to the
        corpora below. Counterexamples and call sequences are elided — reproduce locally, never on mainnet.
      </p>

      {loadErr && (
        <div className="flex items-center gap-3 text-sm text-rose-300 border border-rose-900/60 rounded-lg px-3 py-2 bg-rose-950/20">
          <span className="flex-1">Couldn&apos;t load engine status: {loadErr}</span>
          <button type="button" onClick={() => void load()} className="text-[11px] uppercase tracking-wider text-gold hover:text-gold/80">
            Retry
          </button>
        </div>
      )}

      {offline && cat && (
        <div className="rounded-lg border border-amber-800/50 bg-amber-950/10 p-4 text-xs text-brand-300 leading-relaxed">
          <p className="text-[11px] tracking-[0.2em] uppercase text-amber-200 font-semibold">Offline desk · paste mode</p>
          <p className="mt-2 max-w-3xl">
            {cat.on_vercel
              ? "This deployment runs on Vercel serverless, which ships no engine binaries (Slither, Echidna, Halmos… need solc, foundry or native toolchains)."
              : "No engine binaries were found on this host's PATH or ETH_SCANNER_*_BIN."}{" "}
            The desk still works end to end: run an engine on your own machine or worker, paste the report, and you get
            the same normalized, triaged, prior-art-linked findings.
          </p>
          <ol className="mt-3 grid gap-2 sm:grid-cols-3">
            <li className="rounded-md border border-brand-800/80 bg-brand-950/60 p-2.5">
              <span className="text-gold font-semibold">1 · Install</span>
              <span className="block text-brand-400">Pick an engine card below and copy its install command.</span>
            </li>
            <li className="rounded-md border border-brand-800/80 bg-brand-950/60 p-2.5">
              <span className="text-gold font-semibold">2 · Run + paste</span>
              <span className="block text-brand-400">Run it on your repo and paste the report into the box below.</span>
            </li>
            <li className="rounded-md border border-brand-800/80 bg-brand-950/60 p-2.5">
              <span className="text-gold font-semibold">3 · Triage</span>
              <span className="block text-brand-400">Ranked by severity × confidence × Sherlock prior; export as .md.</span>
            </li>
          </ol>
          <p className="mt-3 text-brand-500">
            No report handy? <span className="text-brand-300">Load sample Slither report</span> fills the paste box
            with an illustrative report so you can see the whole pipeline.
          </p>
        </div>
      )}

      {offline && pasteBox}

      {err && (
        <div className="flex items-center gap-3 text-sm text-rose-300 border border-rose-900/60 rounded-lg px-3 py-2 bg-rose-950/20">
          <span className="flex-1">{err}</span>
          <button type="button" onClick={() => setErr(null)} className="text-[11px] uppercase tracking-wider text-brand-400 hover:text-brand-200">
            Dismiss
          </button>
        </div>
      )}

      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
          <h2 className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold">
            {offline ? "Engines · install locally" : "Engines"}
          </h2>
          {cat && (
            <span className="text-[11px] text-brand-400">
              {cat.summary.installed} installed · {cat.summary.stub} stub · {cat.summary.missing} missing
              {cat.on_vercel ? " · Vercel serverless" : ""}
              <button type="button" onClick={() => void load()} className="ml-3 uppercase tracking-wider text-gold/80 hover:text-gold">
                Refresh
              </button>
            </span>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(cat?.engines ?? []).map((e) => {
            const usable = e.status === "installed";
            return (
              <div
                key={e.id}
                className={`rounded-lg border bg-brand-900/30 p-3 text-xs flex flex-col gap-1 ${
                  usable && picked.has(e.id) ? "border-gold/50" : "border-brand-800/80"
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <label className={`flex items-center gap-2 font-semibold text-brand-50 ${usable ? "cursor-pointer" : ""}`}>
                    {usable && (
                      <input
                        type="checkbox"
                        checked={picked.has(e.id)}
                        onChange={(ev) =>
                          setPicked((prev) => {
                            const next = new Set(prev);
                            if (ev.target.checked) next.add(e.id);
                            else next.delete(e.id);
                            return next;
                          })
                        }
                      />
                    )}
                    {e.name}
                  </label>
                  <span className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${STATUS_STYLE[e.status]}`}>
                    {e.status}
                  </span>
                </span>
                <span className="text-brand-500 uppercase tracking-wider text-[10px]">
                  {e.kind} · {e.target}
                </span>
                <span className="text-brand-300 leading-snug">{e.blurb}</span>
                {e.version && <span className="text-brand-500 truncate">{e.version}</span>}
                {e.reason && !offline && <span className="text-brand-500 leading-snug">{e.reason}</span>}
                <a className="text-gold/80 hover:text-gold truncate" href={e.fork_url} target="_blank" rel="noreferrer">
                  {e.fork}
                </a>
                {!usable && (
                  <span className="mt-1 flex items-start gap-2 rounded border border-brand-800 bg-brand-950/70 px-2 py-1">
                    <code className="flex-1 font-mono text-[10px] text-brand-300 break-all">{e.install}</code>
                    <CopyButton text={e.install} />
                  </span>
                )}
                <span className="text-brand-600 font-mono text-[10px] truncate" title={`Override binary path with ${e.envBin}`}>
                  {e.envBin}
                </span>
              </div>
            );
          })}
          {!cat &&
            !loadErr &&
            Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-36 rounded-lg border border-brand-800/60 bg-brand-900/20 animate-pulse" />
            ))}
        </div>

        {cat && !offline && (
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <label className="text-xs text-brand-400 flex flex-col gap-1">
              Source fixture ({cat.fixtures.length})
              <select
                className="rounded-md border border-brand-700 bg-brand-950 px-2 py-1.5 text-brand-100"
                value={fixture}
                onChange={(e) => setFixture(e.target.value)}
              >
                {cat.fixtures.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={busy || picked.size === 0}
              onClick={() => void post({ engines: Array.from(picked), fixture }, "run")}
              className="px-4 py-2 text-[11px] tracking-[0.15em] uppercase font-semibold rounded-md border border-gold/60 text-gold bg-gold/10 disabled:opacity-40"
            >
              {running === "run" ? "Running…" : `Run ${picked.size || ""} engine${picked.size === 1 ? "" : "s"}`}
            </button>
            {picked.size === 0 && <span className="text-xs text-brand-500">Tick at least one installed engine.</span>}
          </div>
        )}
      </div>

      {!offline && pasteBox}

      {busy && (
        <p role="status" className="text-xs text-gold/90 border border-gold/30 rounded-lg px-3 py-2 bg-gold/5 flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full bg-gold animate-pulse" aria-hidden />
          {running === "paste" ? "Normalizing → classifying → triaging…" : "Running engines (fuzzers can take a minute)…"}
        </p>
      )}

      {runs && (
        <div>
          <h2 className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold mb-2">Run log</h2>
          <ul className="space-y-1 text-xs">
            {runs.map((r) => (
              <li key={r.engine} className="flex flex-wrap gap-2 text-brand-300">
                <span className="font-semibold text-brand-100 w-20">{r.engine}</span>
                <span className={r.status === "ok" ? "text-emerald-300" : r.status === "skipped" ? "text-brand-500" : "text-rose-300"}>
                  {r.status}
                </span>
                <span>{r.findings_count} findings</span>
                <span className="text-brand-500">{(r.duration_ms / 1000).toFixed(1)}s</span>
                {r.reason && <span className="text-brand-500">{r.reason}</span>}
                {r.log_tail && (
                  <pre className="basis-full whitespace-pre-wrap text-[10px] text-brand-500 border-l border-brand-800 pl-2">
                    {r.log_tail}
                  </pre>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {persistInfo && (
        <p className="text-[11px] text-brand-500">
          {persistInfo.ok
            ? `Saved to Supabase · run ${persistInfo.run_id?.slice(0, 8)}… · ${persistInfo.findings_count ?? 0} findings`
            : persistInfo.skipped
              ? "Supabase persist skipped (credentials unset)."
              : `Supabase persist soft-failed: ${persistInfo.error || "unknown"} (desk still works).`}
        </p>
      )}
      {triageErr && <p className="text-xs text-rose-300">{triageErr}</p>}

      {findings && (
        <div>
          <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
            <h2 className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold">
              Findings · funds at risk ({visible.length}
              {visible.length !== sorted.length ? ` of ${sorted.length}` : ""})
            </h2>
            <div className="flex flex-wrap items-center gap-2">
              <select
                aria-label="Filter by class"
                className="rounded-md border border-brand-700 bg-brand-950 px-2 py-1 text-xs text-brand-100"
                value={classFilter}
                onChange={(e) => setClassFilter(e.target.value)}
              >
                <option value="all">all classes</option>
                {classesSeen.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              {sorted.length > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    const md = findingsMarkdown(visible, meta?.source ?? "engine desk");
                    const blob = new Blob([md], { type: "text/markdown" });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = `engine-findings-${Date.now()}.md`;
                    a.click();
                    setTimeout(() => URL.revokeObjectURL(url), 1000);
                  }}
                  className="text-[11px] tracking-[0.08em] uppercase font-semibold text-gold hover:text-gold/80"
                >
                  Download .md
                </button>
              )}
            </div>
          </div>
          {meta && (
            <p className="mb-2 text-[11px] text-brand-500">
              {meta.source}
              {meta.duration_ms != null ? ` · ${meta.duration_ms < 1000 ? `${meta.duration_ms} ms` : `${(meta.duration_ms / 1000).toFixed(1)}s`}` : ""}
            </p>
          )}
          {meta?.warning && (
            <p className="mb-3 text-xs text-amber-200 border border-amber-800/60 rounded-lg px-3 py-2 bg-amber-950/20">
              {meta.warning}
            </p>
          )}
          {sorted.length > 0 && (
            <div className="mb-3 flex flex-wrap gap-2 text-[10px] uppercase tracking-[0.12em]">
              <button
                type="button"
                onClick={() => setSevFilter("all")}
                className={`rounded border px-2 py-1 ${sevFilter === "all" ? "border-gold/60 text-gold" : "border-brand-800 text-brand-400"}`}
              >
                all {sorted.length}
              </button>
              {SEV_ORDER.filter((k) => sevCounts[k]).map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setSevFilter(sevFilter === k ? "all" : k)}
                  className={`rounded border px-2 py-1 ${sevFilter === k ? "border-gold/60" : "border-brand-800"} ${SEV_STYLE[k]}`}
                >
                  {sevCounts[k]} {k}
                </button>
              ))}
            </div>
          )}
          {visible.length === 0 ? (
            <p className="text-xs text-brand-500 border border-dashed border-brand-800 rounded-lg px-3 py-6 text-center">
              {sorted.length > 0
                ? "Nothing matches this filter."
                : meta?.warning
                  ? "Nothing was parsed — check the format above."
                  : "The engine reported no findings. That is not a verdict of safety."}
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-brand-800/80">
              <table className="w-full text-xs">
                <thead className="bg-brand-900/60 text-brand-400 text-left">
                  <tr>
                    <th className="px-3 py-2" title="severity × confidence × Sherlock acceptance prior">Score</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Severity</th>
                    <th className="px-3 py-2">Class</th>
                    <th className="px-3 py-2">Engine · rule</th>
                    <th className="px-3 py-2">Where</th>
                    <th className="px-3 py-2">Evidence · prior art</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((f) => (
                    <tr key={f.id} className="border-t border-brand-800/60 align-top">
                      <td className="px-3 py-2 font-mono text-brand-100">{f.triage}</td>
                      <td className="px-3 py-2">
                        {dbIds[f.id] ? (
                          <select
                            aria-label={`Triage status for ${f.rule}`}
                            className="rounded border border-brand-700 bg-brand-950 px-1.5 py-1 text-[10px] text-brand-100"
                            value={triageStatus[f.id] ?? "open"}
                            disabled={triageBusy === f.id}
                            onChange={(e) => void setFindingTriage(f.id, e.target.value as TriageStatus)}
                          >
                            {TRIAGE_STATUSES.map((s) => (
                              <option key={s} value={s}>
                                {s}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="text-brand-600">—</span>
                        )}
                      </td>
                      <td className={`px-3 py-2 uppercase ${SEV_STYLE[f.severity] ?? ""}`}>
                        {f.severity}
                        <span className="block text-[10px] text-brand-500 normal-case">{f.confidence} conf.</span>
                      </td>
                      <td className="px-3 py-2 text-brand-200" title={cat?.classes?.[f.class]}>
                        {f.class}
                      </td>
                      <td className="px-3 py-2 text-brand-200">
                        {f.engine}
                        <span className="block text-brand-500">{f.rule}</span>
                      </td>
                      <td className="px-3 py-2 text-brand-400 font-mono text-[10px]">
                        {[f.location.contract, f.location.function].filter(Boolean).join(".") || "—"}
                        {f.location.file && (
                          <span className="block">
                            {f.location.file}
                            {f.location.line ? `:${f.location.line}` : ""}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-brand-300 max-w-[420px]">
                        <span className="block whitespace-pre-wrap">{f.evidence}</span>
                        <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                          {f.references.map((r) => (
                            <a key={r.url} href={r.url} target="_blank" rel="noreferrer" className="text-gold/80 hover:text-gold">
                              {r.corpus}: {r.label}
                            </a>
                          ))}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div>
        <h2 className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold mb-3">Corpora</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {(cat?.corpora ?? []).map((c) => (
            <div key={c.id} className="rounded-lg border border-brand-800/80 bg-brand-900/30 p-3 text-xs">
              <a className="font-semibold text-brand-50 hover:text-gold" href={c.fork_url} target="_blank" rel="noreferrer">
                {c.name}
              </a>
              <p className="text-brand-400 mt-1">{c.blurb}</p>
              <p className="text-brand-500 mt-1">{c.classes.join(" · ")}</p>
            </div>
          ))}
        </div>
        {cat?.priors && (
          <p className="mt-3 text-[11px] text-brand-500">
            Triage prior (Sherlock acceptance, CC0):{" "}
            {Object.entries(cat.priors)
              .map(([k, v]) => `${k} ${Math.round(v.rate * 100)}% (n=${v.n})`)
              .join(" · ")}
          </p>
        )}
      </div>
    </section>
  );
}
