/**
 * Engine adapters for the /test multi-engine desk.
 *
 * Pure module: registry metadata + output parsers. No child_process here, so
 * parsers are unit-testable and safe to import anywhere. Execution lives in
 * ./runtime.ts. We never vendor the tool repos into the Next bundle — each
 * adapter shells out to a locally installed binary (built from Shane's fork)
 * or parses output that was produced elsewhere.
 *
 * Funds-at-risk only: fuzz/symbolic counterexamples are reduced to
 * "counterexample found (inputs elided)". No PoC / exploit code is produced.
 */

import { makeFinding, type DeskFinding } from "./findings";

export type EngineKind = "static" | "symbolic" | "fuzz" | "bytecode";
/** source = a single .sol target; harness = the defensive property harness. */
export type EngineTarget = "source" | "harness" | "bytecode";

export type EngineMeta = {
  id: EngineId;
  name: string;
  kind: EngineKind;
  target: EngineTarget;
  fork: string;
  upstream: string;
  /** Binary names tried on PATH, in order. */
  binaries: string[];
  /** Env var that may point at an explicit binary/script path. */
  envBin: string;
  /** Extra tools this engine needs at run time (e.g. solc, forge). */
  requires: string[];
  versionArgs: string[];
  install: string;
  timeoutMs: number;
  blurb: string;
};

export const ENGINE_IDS = [
  "slither",
  "aderyn",
  "achecker",
  "echidna",
  "medusa",
  "ityfuzz",
  "halmos",
  "mythril",
] as const;
export type EngineId = (typeof ENGINE_IDS)[number];

const gh = (repo: string) => `https://github.com/${repo}`;

export const ENGINES: Record<EngineId, EngineMeta> = {
  slither: {
    id: "slither",
    name: "Slither",
    kind: "static",
    target: "source",
    fork: "shanecloonan/slither",
    upstream: "crytic/slither",
    binaries: ["slither"],
    envBin: "ETH_SCANNER_SLITHER_BIN",
    requires: ["solc"],
    versionArgs: ["--version"],
    install: "pipx install git+https://github.com/shanecloonan/slither",
    timeoutMs: 90_000,
    blurb: "Static detectors (reentrancy, arbitrary-send, unchecked-transfer, …) → JSON.",
  },
  aderyn: {
    id: "aderyn",
    name: "Aderyn",
    kind: "static",
    target: "source",
    fork: "shanecloonan/aderyn",
    upstream: "Cyfrin/aderyn",
    binaries: ["aderyn"],
    envBin: "ETH_SCANNER_ADERYN_BIN",
    requires: [],
    versionArgs: ["--version"],
    install: "cargo install --git https://github.com/shanecloonan/aderyn aderyn",
    timeoutMs: 90_000,
    blurb: "Rust AST detectors; high/low issue JSON report.",
  },
  achecker: {
    id: "achecker",
    name: "AChecker",
    kind: "bytecode",
    target: "bytecode",
    fork: "shanecloonan/AChecker",
    upstream: "DependableSystemsLab/AChecker",
    binaries: ["achecker", "achecker.py"],
    envBin: "ETH_SCANNER_ACHECKER_BIN",
    requires: ["solc"],
    versionArgs: ["--help"],
    install: "git clone https://github.com/shanecloonan/AChecker && set ETH_SCANNER_ACHECKER_BIN=<clone>/bin/achecker.py",
    timeoutMs: 120_000,
    blurb: "Access-control checks on runtime bytecode (who can move value).",
  },
  echidna: {
    id: "echidna",
    name: "Echidna",
    kind: "fuzz",
    target: "harness",
    fork: "shanecloonan/echidna",
    upstream: "crytic/echidna",
    binaries: ["echidna", "echidna-test"],
    envBin: "ETH_SCANNER_ECHIDNA_BIN",
    requires: ["solc"],
    versionArgs: ["--version"],
    install: "Release binary from https://github.com/shanecloonan/echidna/releases (or nix build)",
    timeoutMs: 120_000,
    blurb: "Property fuzzing over the defensive solvency / conservation harness.",
  },
  medusa: {
    id: "medusa",
    name: "Medusa",
    kind: "fuzz",
    target: "harness",
    fork: "shanecloonan/medusa",
    upstream: "crytic/medusa",
    binaries: ["medusa"],
    envBin: "ETH_SCANNER_MEDUSA_BIN",
    requires: ["solc"],
    versionArgs: ["--version"],
    install: "go install github.com/shanecloonan/medusa@latest (needs crytic-compile + solc)",
    timeoutMs: 120_000,
    blurb: "Parallel coverage-guided fuzzing of the same property harness.",
  },
  ityfuzz: {
    id: "ityfuzz",
    name: "ityfuzz",
    kind: "fuzz",
    target: "harness",
    fork: "shanecloonan/ityfuzz",
    upstream: "fuzzland/ityfuzz",
    binaries: ["ityfuzz"],
    envBin: "ETH_SCANNER_ITYFUZZ_BIN",
    requires: ["solc"],
    versionArgs: ["--version"],
    install: "cargo build --release in a clone of https://github.com/shanecloonan/ityfuzz",
    timeoutMs: 90_000,
    blurb: "Snapshot fuzzer; offchain mode against compiled harness artifacts.",
  },
  halmos: {
    id: "halmos",
    name: "Halmos",
    kind: "symbolic",
    target: "harness",
    fork: "shanecloonan/halmos",
    upstream: "a16z/halmos",
    binaries: ["halmos"],
    envBin: "ETH_SCANNER_HALMOS_BIN",
    requires: ["forge"],
    versionArgs: ["--version"],
    install: "uv tool install git+https://github.com/shanecloonan/halmos (needs foundry)",
    timeoutMs: 150_000,
    blurb: "Symbolic check_* proofs of the conservation invariants.",
  },
  mythril: {
    id: "mythril",
    name: "Mythril",
    kind: "symbolic",
    target: "source",
    fork: "shanecloonan/mythril",
    upstream: "ConsenSysDiligence/mythril",
    binaries: ["myth"],
    envBin: "ETH_SCANNER_MYTHRIL_BIN",
    requires: ["solc"],
    versionArgs: ["version"],
    install: "pipx install git+https://github.com/shanecloonan/mythril",
    timeoutMs: 150_000,
    blurb: "Symbolic execution; SWC-tagged issues (tx sequences dropped).",
  },
};

export function engineCatalog() {
  return ENGINE_IDS.map((id) => {
    const e = ENGINES[id];
    return { ...e, fork_url: gh(e.fork), upstream_url: gh(e.upstream) };
  });
}

export function isEngineId(v: unknown): v is EngineId {
  return typeof v === "string" && (ENGINE_IDS as readonly string[]).includes(v);
}

// ---------------------------------------------------------------------------
// Parsers. Each takes raw stdout (or report file text) and returns findings.
// They must never throw on garbage — return [] instead.
// ---------------------------------------------------------------------------

function safeJson(text: string): unknown {
  const t = (text || "").trim();
  if (!t) return null;
  try {
    return JSON.parse(t);
  } catch {
    // Some tools print banners before JSON; try the outermost object.
    const start = t.indexOf("{");
    const end = t.lastIndexOf("}");
    if (start >= 0 && end > start) {
      try {
        return JSON.parse(t.slice(start, end + 1));
      } catch {
        return null;
      }
    }
    return null;
  }
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

export function parseSlither(text: string): DeskFinding[] {
  const data = safeJson(text);
  if (!isObj(data)) return [];
  const results = isObj(data.results) ? data.results : {};
  return arr(results.detectors).filter(isObj).map((d) => {
    const elements = arr(d.elements).filter(isObj);
    const fn = elements.find((e) => e.type === "function") ?? elements[0];
    const sm = fn && isObj(fn.source_mapping) ? fn.source_mapping : {};
    const tsf = fn && isObj(fn.type_specific_fields) ? fn.type_specific_fields : {};
    const parent = isObj(tsf.parent) ? tsf.parent : {};
    const lines = arr(sm.lines);
    return makeFinding({
      engine: "slither",
      rule: str(d.check) ?? "unknown",
      title: str(d.check) ?? "slither finding",
      severity: d.impact,
      confidence: d.confidence,
      location: {
        file: str(sm.filename_relative) ?? str(sm.filename_short),
        line: num(lines[0]),
        contract: str(parent.name),
        function: fn?.type === "function" ? str(fn.name) : null,
      },
      evidence: d.description,
    });
  });
}

export function parseAderyn(text: string): DeskFinding[] {
  const data = safeJson(text);
  if (!isObj(data)) return [];
  const out: DeskFinding[] = [];
  for (const [bucket, severity] of [
    ["critical_issues", "critical"],
    ["high_issues", "high"],
    ["medium_issues", "medium"],
    ["low_issues", "low"],
  ] as const) {
    const group = isObj(data[bucket]) ? (data[bucket] as Obj) : null;
    for (const issue of arr(group?.issues).filter(isObj)) {
      const instances = arr(issue.instances).filter(isObj);
      const rule = str(issue.detector_name) ?? str(issue.title) ?? "aderyn";
      const list = instances.length ? instances : [{} as Obj];
      for (const inst of list.slice(0, 20)) {
        out.push(
          makeFinding({
            engine: "aderyn",
            rule,
            title: str(issue.title) ?? rule,
            severity,
            confidence: "medium",
            location: { file: str(inst.contract_path), line: num(inst.line_no) },
            evidence: issue.description,
          }),
        );
      }
    }
  }
  return out;
}

export function parseMythril(text: string): DeskFinding[] {
  const data = safeJson(text);
  if (!isObj(data)) return [];
  return arr(data.issues).filter(isObj).map((i) => {
    const swc = str(i["swc-id"]) ?? str(i.swcID) ?? "";
    return makeFinding({
      engine: "mythril",
      rule: swc ? `SWC-${swc.replace(/^SWC-/i, "")}` : str(i.title) ?? "mythril",
      title: str(i.title) ?? "mythril issue",
      severity: i.severity,
      confidence: "medium",
      location: {
        file: str(i.filename),
        line: num(i.lineno),
        contract: str(i.contract),
        function: str(i.function),
      },
      // description only — tx_sequence / calldata intentionally dropped.
      evidence: str(i.description) ?? str(i.description_head),
      classHint: swc ? `swc-${swc.replace(/^SWC-/i, "")}` : undefined,
    });
  });
}

/** AChecker prints free text. Keep lines that report a violation. */
export function parseAChecker(text: string): DeskFinding[] {
  const out: DeskFinding[] = [];
  const lines = (text || "").split(/\r?\n/);
  for (const line of lines) {
    const l = line.trim();
    if (!l) continue;
    if (/no (access[- ]control )?vulnerab|not vulnerable|safe\b/i.test(l)) continue;
    if (!/vulnerab|violation|unprotected|access[- ]control (bug|issue)/i.test(l)) continue;
    const pc = l.match(/pc[:= ]+(0x[0-9a-f]+|\d+)/i)?.[1] ?? null;
    out.push(
      makeFinding({
        engine: "achecker",
        rule: /selfdestruct|suicide/i.test(l) ? "unprotected-selfdestruct" : "access-control",
        title: "Access-control enforcement gap on a value-moving path",
        severity: "high",
        confidence: "medium",
        location: { function: pc ? `pc ${pc}` : null },
        evidence: l,
        classHint: "access-control",
      }),
    );
  }
  return out;
}

/** Echidna text format: `echidna_prop: passing` / `echidna_prop: failed!💥`. */
export function parseEchidna(text: string): DeskFinding[] {
  const out: DeskFinding[] = [];
  for (const line of (text || "").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][\w]*)(?:\([^)]*\))?\s*:\s*(failed|FAILED|falsified)/);
    if (!m) continue;
    out.push(
      makeFinding({
        engine: "echidna",
        rule: m[1],
        title: `Property ${m[1]} falsified`,
        severity: "high",
        confidence: "high",
        location: { function: m[1] },
        evidence: `Echidna falsified ${m[1]} — counterexample found (call sequence elided; reproduce locally in a sandbox).`,
        classHint: "invariant",
      }),
    );
  }
  return out;
}

/** Medusa: `[FAILED] Property Test: Contract.prop()` / assertion tests. */
export function parseMedusa(text: string): DeskFinding[] {
  const out: DeskFinding[] = [];
  for (const line of (text || "").split(/\r?\n/)) {
    const m = line.match(/\[FAILED\]\s*(Property|Assertion|Optimization)?\s*Test:\s*([\w.]+)\(/i);
    if (!m) continue;
    const full = m[2];
    const [contract, fn] = full.includes(".") ? full.split(".", 2) : [null, full];
    out.push(
      makeFinding({
        engine: "medusa",
        rule: fn ?? full,
        title: `${m[1] ?? "Property"} test ${full} failed`,
        severity: "high",
        confidence: "high",
        location: { contract, function: fn ?? full },
        evidence: `Medusa failed ${full} — counterexample found (call sequence elided).`,
        classHint: "invariant",
      }),
    );
  }
  return out;
}

/** ityfuzz: objective / violation lines. Reproducer traces are elided. */
export function parseItyfuzz(text: string): DeskFinding[] {
  const out: DeskFinding[] = [];
  const seen = new Set<string>();
  for (const line of (text || "").split(/\r?\n/)) {
    const l = line.replace(/\x1b\[[0-9;]*m/g, "").trim();
    const m = l.match(/(?:Found (?:a )?(?:violation|vulnerabilit(?:y|ies)|bug)s?|Objective(?: found)?|Oracle)\W+(.*)$/i);
    if (!m) continue;
    const what = (m[1] || "objective").slice(0, 120) || "objective";
    if (seen.has(what)) continue;
    seen.add(what);
    out.push(
      makeFinding({
        engine: "ityfuzz",
        rule: what.split(/\s+/)[0]?.toLowerCase() || "objective",
        title: `ityfuzz objective hit: ${what}`,
        severity: "high",
        confidence: "medium",
        evidence: `${what} — reproducer trace elided.`,
        classHint: what,
      }),
    );
  }
  return out;
}

/** Halmos: `[FAIL] check_x() (paths: …)`. Counterexample values are elided. */
export function parseHalmos(text: string): DeskFinding[] {
  const out: DeskFinding[] = [];
  let contract: string | null = null;
  for (const line of (text || "").split(/\r?\n/)) {
    const l = line.replace(/\x1b\[[0-9;]*m/g, "");
    const c = l.match(/Running \d+ tests? for .*?:(\w+)/);
    if (c) contract = c[1];
    const m = l.match(/\[(FAIL|TIMEOUT|ERROR)\]\s*(\w+)\(/);
    if (!m) continue;
    const failed = m[1] === "FAIL";
    out.push(
      makeFinding({
        engine: "halmos",
        rule: m[2],
        title: failed ? `Symbolic check ${m[2]} has a counterexample` : `Symbolic check ${m[2]} ${m[1].toLowerCase()}`,
        severity: failed ? "high" : "info",
        confidence: failed ? "high" : "low",
        location: { contract, function: m[2] },
        evidence: failed
          ? `Halmos found a counterexample for ${m[2]} (inputs elided).`
          : `Halmos ${m[1]} on ${m[2]} — inconclusive, not a finding.`,
        classHint: "invariant",
      }),
    );
  }
  return out;
}

export const PARSERS: Record<EngineId, (text: string) => DeskFinding[]> = {
  slither: parseSlither,
  aderyn: parseAderyn,
  achecker: parseAChecker,
  echidna: parseEchidna,
  medusa: parseMedusa,
  ityfuzz: parseItyfuzz,
  halmos: parseHalmos,
  mythril: parseMythril,
};
