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

const SEV_STYLE: Record<string, string> = {
  critical: "text-rose-200",
  high: "text-rose-300",
  medium: "text-amber-200",
  low: "text-brand-200",
  info: "text-brand-400",
};

export default function EnginesPanel() {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [fixture, setFixture] = useState("open_vault");
  const [running, setRunning] = useState(false);
  const [runs, setRuns] = useState<EngineRun[] | null>(null);
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [pasteEngine, setPasteEngine] = useState("slither");
  const [paste, setPaste] = useState("");
  const [classFilter, setClassFilter] = useState("all");

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/test/engines", { cache: "no-store" });
      const j = (await r.json()) as Catalog;
      setCat(j);
      setPicked((prev) => (prev.size ? prev : new Set(j.engines.filter((e) => e.status === "installed").map((e) => e.id))));
      if (j.fixtures.length && !j.fixtures.includes(fixture)) setFixture(j.fixtures[0]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "failed to load engines");
    }
  }, [fixture]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function post(body: unknown) {
    setRunning(true);
    setErr(null);
    try {
      const r = await fetch("/api/test/engines", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || `HTTP ${r.status}`);
      setFindings(j.findings);
      setRuns(j.runs ?? null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "request failed");
    } finally {
      setRunning(false);
    }
  }

  const visible = useMemo(
    () => (findings ?? []).filter((f) => classFilter === "all" || f.class === classFilter),
    [findings, classFilter],
  );
  const classesSeen = useMemo(() => Array.from(new Set((findings ?? []).map((f) => f.class))).sort(), [findings]);

  return (
    <section className="mt-8 space-y-8">
      <p className="text-sm text-brand-400 max-w-3xl leading-relaxed">
        One desk, eight engines, one finding schema. Static and symbolic engines read a local fixture; fuzzers and
        Halmos run the defensive conservation harness (<code className="text-brand-200">eth-scanner/research/fuzz</code>).
        Every finding is framed as <span className="text-gold">funds at risk</span> and cross-referenced to the
        corpora below. Counterexamples and call sequences are elided — reproduce locally, never on mainnet.
      </p>

      {err && <p className="text-sm text-rose-300">{err}</p>}

      <div>
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold">Engines</h2>
          {cat && (
            <span className="text-[11px] text-brand-400">
              {cat.summary.installed} installed · {cat.summary.stub} stub · {cat.summary.missing} missing
              {cat.on_vercel ? " · Vercel serverless (no engine binaries)" : ""}
            </span>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(cat?.engines ?? []).map((e) => (
            <label
              key={e.id}
              className={`rounded-lg border bg-brand-900/30 p-3 text-xs flex flex-col gap-1 cursor-pointer ${
                picked.has(e.id) ? "border-gold/50" : "border-brand-800/80"
              }`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 font-semibold text-brand-50">
                  <input
                    type="checkbox"
                    checked={picked.has(e.id)}
                    disabled={e.status !== "installed"}
                    onChange={(ev) =>
                      setPicked((prev) => {
                        const next = new Set(prev);
                        if (ev.target.checked) next.add(e.id);
                        else next.delete(e.id);
                        return next;
                      })
                    }
                  />
                  {e.name}
                </span>
                <span className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${STATUS_STYLE[e.status]}`}>
                  {e.status}
                </span>
              </span>
              <span className="text-brand-500 uppercase tracking-wider text-[10px]">
                {e.kind} · {e.target}
              </span>
              <span className="text-brand-300 leading-snug">{e.blurb}</span>
              {e.version && <span className="text-brand-500 truncate">{e.version}</span>}
              {e.reason && <span className="text-brand-500 leading-snug">{e.reason}</span>}
              <a className="text-gold/80 hover:text-gold truncate" href={e.fork_url} target="_blank" rel="noreferrer">
                {e.fork}
              </a>
              <span className="text-brand-600 font-mono text-[10px] truncate" title={e.install}>
                {e.envBin}
              </span>
            </label>
          ))}
          {!cat && <p className="text-xs text-brand-500">Loading engine status…</p>}
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-3">
          <label className="text-xs text-brand-400 flex flex-col gap-1">
            Source fixture (static / symbolic / bytecode)
            <select
              className="rounded-md border border-brand-700 bg-brand-950 px-2 py-1.5 text-brand-100"
              value={fixture}
              onChange={(e) => setFixture(e.target.value)}
            >
              {(cat?.fixtures ?? []).map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={running || picked.size === 0}
            onClick={() => void post({ engines: Array.from(picked), fixture })}
            className="px-4 py-2 text-[11px] tracking-[0.15em] uppercase font-semibold rounded-md border border-gold/60 text-gold bg-gold/10 disabled:opacity-40"
          >
            {running ? "Running…" : `Run ${picked.size || ""} engine${picked.size === 1 ? "" : "s"}`}
          </button>
          <button
            type="button"
            onClick={() => void load()}
            className="px-3 py-2 text-[11px] tracking-[0.15em] uppercase rounded-md border border-brand-700 text-brand-300 hover:bg-brand-900"
          >
            Refresh status
          </button>
          {cat && cat.summary.installed === 0 && (
            <span className="text-xs text-brand-500">
              No engines installed here — run them on a worker and paste the output below.
            </span>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-brand-800/80 bg-brand-900/30 p-4">
        <h2 className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold mb-2">Paste engine output</h2>
        <p className="text-xs text-brand-400 mb-3">
          Ran an engine elsewhere? Paste its report (Slither / Aderyn / Mythril JSON, or Echidna / Medusa / ityfuzz /
          Halmos / AChecker text) to normalize it into the same schema. 2 MB max; nothing is stored.
        </p>
        <div className="flex flex-wrap gap-3 items-start">
          <select
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
            className="flex-1 min-w-[240px] h-28 rounded-md border border-brand-700 bg-brand-950 p-2 font-mono text-[11px] text-brand-100"
            placeholder="slither . --json -  → paste here"
            value={paste}
            onChange={(e) => setPaste(e.target.value)}
          />
          <button
            type="button"
            disabled={running || !paste.trim()}
            onClick={() => void post({ engine: pasteEngine, output: paste })}
            className="px-4 py-2 text-[11px] tracking-[0.15em] uppercase font-semibold rounded-md border border-brand-600 text-brand-100 hover:bg-brand-900 disabled:opacity-40"
          >
            Normalize
          </button>
        </div>
      </div>

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

      {findings && (
        <div>
          <div className="flex items-baseline justify-between mb-2">
            <h2 className="text-[11px] tracking-[0.2em] uppercase text-gold/80 font-semibold">
              Findings · funds at risk ({visible.length})
            </h2>
            <select
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
          </div>
          {visible.length === 0 ? (
            <p className="text-xs text-brand-500">No findings. That is not a verdict of safety.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-brand-800/80">
              <table className="w-full text-xs">
                <thead className="bg-brand-900/60 text-brand-400 text-left">
                  <tr>
                    <th className="px-3 py-2">Triage</th>
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
                            <a
                              key={r.url}
                              href={r.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-gold/80 hover:text-gold"
                            >
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
