/**
 * Server-only engine detection + execution for the /test multi-engine desk.
 *
 * - Detects each engine binary (env override → PATH → common tool dirs).
 * - Status: installed | missing | stub (adapter present, prerequisite absent
 *   or disabled). Vercel serverless ships none of these binaries, so the desk
 *   degrades to "missing" there and still parses pasted engine output.
 * - Runs engines with no shell, a scrubbed env (no API keys / service roles),
 *   a temp workdir, and a hard timeout. Targets are whitelisted local
 *   fixtures or the defensive property harness only.
 */

import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import path from "node:path";
import { crossReference, triageScore } from "./corpora";
import { ENGINE_IDS, ENGINES, PARSERS, type EngineId, type EngineMeta } from "./engines";
import { dedupeFindings, severityCounts, sortFindings, type DeskFinding, type Severity } from "./findings";

export type EngineStatus = "installed" | "missing" | "stub";

export type EngineStatusRow = {
  id: EngineId;
  status: EngineStatus;
  binary: string | null;
  version: string | null;
  reason: string | null;
};

const SECRETISH =
  /(?:eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)|(?:sk[_-][A-Za-z0-9]{16,})|(?:Bearer\s+[A-Za-z0-9._\-]+)|((?:api[_-]?key|secret|token|password|service[_-]?role)[^\s=]*\s*[:=]\s*)\S+/gi;

export function redact(s: string): string {
  return s.replace(SECRETISH, (_m, pre) => (pre ? `${pre}[redacted]` : "[redacted]"));
}

export function scannerDir(): string {
  return path.join(process.cwd(), "eth-scanner");
}

export function fixturesDir(): string {
  return path.join(scannerDir(), "tests", "fixtures");
}

export function harnessDir(): string {
  return path.join(scannerDir(), "research", "fuzz");
}

function extraToolDirs(): string[] {
  const h = homedir();
  return [".local/bin", ".foundry/bin", ".cargo/bin", "go/bin", ".nix-profile/bin"].map((d) => path.join(h, d));
}

function isExecutableFile(p: string): boolean {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}

export function which(name: string): string | null {
  const dirs = [...(process.env.PATH || "").split(path.delimiter).filter(Boolean), ...extraToolDirs()];
  for (const d of dirs) {
    const p = path.join(d, name);
    if (isExecutableFile(p)) return p;
  }
  return null;
}

function resolveEngineBinary(e: EngineMeta): string | null {
  const override = process.env[e.envBin]?.trim();
  if (override) return isExecutableFile(override) ? override : null;
  for (const b of e.binaries) {
    const p = which(b);
    if (p) return p;
  }
  return null;
}

function disabledEngines(): Set<string> {
  return new Set(
    (process.env.ETH_SCANNER_ENGINES_DISABLED || "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  );
}

/** Spawn args for a binary; *.py scripts run through python3. */
function commandFor(bin: string, args: string[]): [string, string[]] {
  if (bin.endsWith(".py")) return [which("python3") ?? "python3", [bin, ...args]];
  return [bin, args];
}

function probeVersion(bin: string, args: string[]): string | null {
  try {
    const [cmd, argv] = commandFor(bin, args);
    const r = spawnSync(cmd, argv, { encoding: "utf8", timeout: 8_000, env: scrubbedEnv() });
    const text = `${r.stdout || ""}\n${r.stderr || ""}`.trim();
    const line = text.split(/\r?\n/).find((l) => /\d+\.\d+/.test(l)) ?? text.split(/\r?\n/)[0];
    return line ? redact(line).slice(0, 80) : null;
  } catch {
    return null;
  }
}

let statusCache: { at: number; rows: EngineStatusRow[] } | null = null;

export function engineStatuses(force = false): EngineStatusRow[] {
  if (!force && statusCache && Date.now() - statusCache.at < 60_000) return statusCache.rows;
  const disabled = disabledEngines();
  const onVercel = Boolean(process.env.VERCEL);
  const rows = ENGINE_IDS.map((id): EngineStatusRow => {
    const e = ENGINES[id];
    if (disabled.has(id)) {
      return { id, status: "stub", binary: null, version: null, reason: "disabled via ETH_SCANNER_ENGINES_DISABLED" };
    }
    const bin = resolveEngineBinary(e);
    if (!bin) {
      return {
        id,
        status: "missing",
        binary: null,
        version: null,
        reason: onVercel
          ? "not bundled on Vercel serverless — run on a worker with the fork installed, or paste its output"
          : `not found (${e.envBin} or PATH: ${e.binaries.join(", ")})`,
      };
    }
    const missingReq = e.requires.filter((r) => !which(r));
    if (missingReq.length) {
      return { id, status: "stub", binary: bin, version: null, reason: `adapter ready; needs ${missingReq.join(", ")}` };
    }
    return { id, status: "installed", binary: bin, version: probeVersion(bin, e.versionArgs), reason: null };
  });
  statusCache = { at: Date.now(), rows };
  return rows;
}

/** Only PATH/HOME/locale reach engine processes — never API keys. */
function scrubbedEnv(): NodeJS.ProcessEnv {
  const env: Record<string, string | undefined> = {
    PATH: [process.env.PATH || "", ...extraToolDirs()].filter(Boolean).join(path.delimiter),
    HOME: process.env.HOME || tmpdir(),
    LANG: process.env.LANG || "C.UTF-8",
    NO_COLOR: "1",
  };
  for (const k of ["SOLC_VERSION", "SVM_HOME", "FOUNDRY_DIR"]) if (process.env[k]) env[k] = process.env[k];
  return env as NodeJS.ProcessEnv;
}

export function sourceFixtureCatalog(): string[] {
  try {
    return readdirSync(fixturesDir())
      .filter((f) => /^[a-z0-9_]+\.sol$/.test(f))
      .map((f) => f.replace(/\.sol$/, ""))
      .sort();
  } catch {
    return [];
  }
}

export function resolveSourceFixture(id: unknown): string | null {
  if (typeof id !== "string" || !/^[a-z0-9_]{1,80}$/.test(id)) return null;
  const p = path.join(fixturesDir(), `${id}.sol`);
  return existsSync(p) ? p : null;
}

type Spawned = { code: number | null; stdout: string; stderr: string; timedOut: boolean };

const MAX_CAPTURE = 4 * 1024 * 1024;

function run(bin: string, args: string[], cwd: string, timeoutMs: number): Promise<Spawned> {
  return new Promise((resolve) => {
    const [cmd, argv] = commandFor(bin, args);
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let child;
    try {
      child = spawn(cmd, argv, { cwd, env: scrubbedEnv(), stdio: ["ignore", "pipe", "pipe"] });
    } catch (err) {
      resolve({ code: -1, stdout: "", stderr: String(err), timedOut: false });
      return;
    }
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGKILL");
    }, timeoutMs);
    child.stdout?.on("data", (d: Buffer) => {
      if (stdout.length < MAX_CAPTURE) stdout += d.toString("utf8");
    });
    child.stderr?.on("data", (d: Buffer) => {
      if (stderr.length < MAX_CAPTURE) stderr += d.toString("utf8");
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ code: -1, stdout, stderr: `${stderr}\n${err.message}`, timedOut });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr, timedOut });
    });
  });
}

const HARNESS_PROPS = [
  ["echidna/VaultProperties.sol", "VaultProperties"],
  ["echidna/LendingProperties.sol", "LendingProperties"],
  ["echidna/StakingProperties.sol", "StakingProperties"],
] as const;

/** solc --bin-runtime → largest runtime blob (the main contract). */
function compileRuntime(file: string, cwd: string): string | null {
  const solc = which("solc");
  if (!solc) return null;
  const r = spawnSync(solc, ["--bin-runtime", file], { cwd, encoding: "utf8", timeout: 60_000, env: scrubbedEnv() });
  const blobs = (r.stdout || "").match(/Binary of the runtime part:\s*\n([0-9a-f]+)/g) ?? [];
  const hex = blobs.map((b) => b.replace(/^[\s\S]*:\s*\n/, "")).sort((a, b) => b.length - a.length)[0];
  return hex || null;
}

export type EngineRun = {
  engine: EngineId;
  status: "ok" | "skipped" | "error" | "timeout";
  reason: string | null;
  duration_ms: number;
  exit_code: number | null;
  findings_count: number;
  log_tail: string;
};

async function runOne(
  e: EngineMeta,
  bin: string,
  ctx: { tmp: string; sourceFile: string | null },
): Promise<{ run: Omit<EngineRun, "engine" | "duration_ms">; findings: DeskFinding[] }> {
  const parse = PARSERS[e.id];
  const tail = (s: string) => redact(s.split(/\r?\n/).filter(Boolean).slice(-6).join("\n")).slice(-800);
  const harness = path.join(ctx.tmp, "harness");

  if (e.target === "harness") {
    cpSync(harnessDir(), harness, { recursive: true });
  } else if (!ctx.sourceFile) {
    return { run: { status: "skipped", reason: "needs a source fixture", exit_code: null, findings_count: 0, log_tail: "" }, findings: [] };
  }
  const srcName = ctx.sourceFile ? path.basename(ctx.sourceFile) : "";
  if (ctx.sourceFile) {
    mkdirSync(path.join(ctx.tmp, "src"), { recursive: true });
    cpSync(ctx.sourceFile, path.join(ctx.tmp, "src", srcName));
  }

  let outputs: Spawned[] = [];
  let reportText: string | null = null;
  switch (e.id) {
    case "slither":
      outputs = [await run(bin, [path.join("src", srcName), "--json", "-", "--disable-color"], ctx.tmp, e.timeoutMs)];
      break;
    case "aderyn": {
      writeFileSync(path.join(ctx.tmp, "foundry.toml"), '[profile.default]\nsrc = "src"\n');
      const report = path.join(ctx.tmp, "aderyn-report.json");
      outputs = [await run(bin, [ctx.tmp, "--output", report], ctx.tmp, e.timeoutMs)];
      reportText = existsSync(report) ? readFileSync(report, "utf8") : null;
      break;
    }
    case "mythril":
      outputs = [
        await run(
          bin,
          ["analyze", path.join("src", srcName), "-o", "json", "--execution-timeout", "60", "--solver-timeout", "10000"],
          ctx.tmp,
          e.timeoutMs,
        ),
      ];
      break;
    case "achecker": {
      const hex = compileRuntime(path.join("src", srcName), ctx.tmp);
      if (!hex) {
        return { run: { status: "error", reason: "solc could not produce runtime bytecode", exit_code: null, findings_count: 0, log_tail: "" }, findings: [] };
      }
      const binFile = path.join(ctx.tmp, "target.bin-runtime");
      writeFileSync(binFile, hex);
      outputs = [await run(bin, ["-f", binFile, "-b"], ctx.tmp, e.timeoutMs)];
      break;
    }
    case "echidna":
      for (const [file, contract] of HARNESS_PROPS) {
        outputs.push(
          await run(bin, [file, "--contract", contract, "--config", "echidna.yaml", "--format", "text"], harness, Math.floor(e.timeoutMs / 3)),
        );
      }
      break;
    case "medusa":
      for (const [file, contract] of HARNESS_PROPS) {
        const cfg = path.join(harness, `medusa-${contract}.json`);
        writeFileSync(
          cfg,
          JSON.stringify({
            fuzzing: {
              workers: 2,
              timeout: 30,
              testLimit: 20000,
              targetContracts: [contract],
              testing: {
                propertyTesting: { enabled: true, testPrefixes: ["echidna_"] },
                assertionTesting: { enabled: false },
                optimizationTesting: { enabled: false },
              },
            },
            compilation: { platform: "crytic-compile", platformConfig: { target: file, args: [] } },
          }),
        );
        outputs.push(await run(bin, ["fuzz", "--config", cfg, "--no-color"], harness, Math.floor(e.timeoutMs / 3)));
      }
      break;
    case "ityfuzz": {
      const solc = which("solc");
      const build = path.join(harness, "build");
      for (const [file] of HARNESS_PROPS) {
        spawnSync(solc ?? "solc", ["--abi", "--bin", "--overwrite", "-o", build, file], { cwd: harness, timeout: 60_000, env: scrubbedEnv() });
      }
      if (!existsSync(build)) {
        return { run: { status: "error", reason: "solc did not emit harness artifacts", exit_code: null, findings_count: 0, log_tail: "" }, findings: [] };
      }
      outputs = [await run(bin, ["evm", "-t", "build/*"], harness, e.timeoutMs)];
      break;
    }
    case "halmos":
      outputs = [await run(bin, ["--root", harness, "--function", "check_"], harness, e.timeoutMs)];
      break;
  }

  const combined = outputs.map((o) => `${o.stdout}\n${o.stderr}`).join("\n");
  const parseInput =
    reportText ??
    (e.id === "slither" || e.id === "mythril" ? outputs.map((o) => o.stdout).join("\n") : combined);
  const findings = parse(parseInput);
  const anyTimeout = outputs.some((o) => o.timedOut);
  const lastCode = outputs.length ? outputs[outputs.length - 1].code : null;
  const crashed = outputs.every((o) => o.code === -1);
  const status: EngineRun["status"] = crashed
    ? "error"
    : anyTimeout && e.id !== "ityfuzz"
      ? "timeout"
      : "ok";
  return {
    run: {
      status,
      reason: e.id === "ityfuzz" && anyTimeout ? "time-boxed campaign (expected)" : null,
      exit_code: lastCode,
      findings_count: findings.length,
      log_tail: findings.length ? "" : tail(combined),
    },
    findings,
  };
}

export type DeskRunInput = { engines?: unknown; fixture?: unknown };

export type DeskRunResult = {
  ok: true;
  target: { fixture: string | null; harness: boolean };
  runs: EngineRun[];
  findings: (DeskFinding & { triage: number })[];
  severity_counts: Record<Severity, number>;
  duration_ms: number;
};

/** Dedupe → cross-reference → triage → rank (severity, then triage desc). */
export function finalizeFindings(list: DeskFinding[]): (DeskFinding & { triage: number })[] {
  return sortFindings(crossReference(dedupeFindings(list)).map((f) => ({ ...f, triage: triageScore(f) })));
}

export async function runDesk(input: DeskRunInput): Promise<DeskRunResult | { ok: false; error: string }> {
  const t0 = Date.now();
  const fixture = input.fixture == null || input.fixture === "" ? null : String(input.fixture);
  const sourceFile = fixture ? resolveSourceFixture(fixture) : null;
  if (fixture && !sourceFile) return { ok: false, error: "unknown fixture" };

  const statuses = engineStatuses(true);
  const requested = Array.isArray(input.engines)
    ? input.engines.filter((x): x is EngineId => typeof x === "string" && (ENGINE_IDS as readonly string[]).includes(x))
    : statuses.filter((s) => s.status === "installed").map((s) => s.id);
  if (!requested.length) {
    const installed = statuses.filter((s) => s.status === "installed").length;
    return {
      ok: false,
      error: installed
        ? "no engines selected — tick at least one installed engine"
        : "no engines are installed on this host — run one on a worker and paste its output instead",
    };
  }

  const runs: EngineRun[] = [];
  let findings: DeskFinding[] = [];
  for (const id of requested) {
    const e = ENGINES[id];
    const st = statuses.find((s) => s.id === id)!;
    const started = Date.now();
    if (st.status !== "installed" || !st.binary) {
      runs.push({ engine: id, status: "skipped", reason: `${st.status}: ${st.reason ?? ""}`.trim(), duration_ms: 0, exit_code: null, findings_count: 0, log_tail: "" });
      continue;
    }
    if (e.target !== "harness" && !sourceFile) {
      runs.push({ engine: id, status: "skipped", reason: "pick a source fixture for static/symbolic engines", duration_ms: 0, exit_code: null, findings_count: 0, log_tail: "" });
      continue;
    }
    const tmp = path.join(tmpdir(), `eth-desk-${id}-${randomBytes(4).toString("hex")}`);
    mkdirSync(tmp, { recursive: true });
    try {
      const out = await runOne(e, st.binary, { tmp, sourceFile });
      runs.push({ engine: id, duration_ms: Date.now() - started, ...out.run });
      findings = findings.concat(out.findings);
    } catch (err) {
      runs.push({
        engine: id,
        status: "error",
        reason: redact(err instanceof Error ? err.message : String(err)).slice(0, 300),
        duration_ms: Date.now() - started,
        exit_code: null,
        findings_count: 0,
        log_tail: "",
      });
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  }

  const final = finalizeFindings(findings);
  return {
    ok: true,
    target: { fixture, harness: requested.some((id) => ENGINES[id].target === "harness") },
    runs,
    findings: final,
    severity_counts: severityCounts(final),
    duration_ms: Date.now() - t0,
  };
}

const MAX_PASTE = 2 * 1024 * 1024;

/** What each parser expects, for empty-result hints. */
export const PASTE_FORMAT: Record<EngineId, string> = {
  slither: "Slither JSON (slither . --json -)",
  aderyn: "Aderyn JSON report (aderyn . -o report.json)",
  achecker: "AChecker text output",
  echidna: "Echidna text output (property failed / passing lines)",
  medusa: "Medusa text output",
  mythril: "Mythril JSON (myth analyze -o json)",
  ityfuzz: "ityfuzz text output",
  halmos: "Halmos text output ([FAIL] / [PASS] lines)",
};

export type PasteResult = {
  ok: true;
  engine: EngineId;
  requested_engine: EngineId;
  detected: boolean;
  findings: (DeskFinding & { triage: number })[];
  severity_counts: Record<Severity, number>;
  warning: string | null;
};

/**
 * Normalize output produced elsewhere (e.g. a local slither --json run).
 * If the chosen parser recognizes nothing, try the others so a mis-picked
 * engine in the dropdown still normalizes — and say so instead of silently
 * returning an empty (and misleadingly "clean") table.
 */
export function parsePasted(engine: EngineId, text: string): PasteResult {
  const clipped = text.length > MAX_PASTE ? text.slice(0, MAX_PASTE) : text;
  let used: EngineId = engine;
  let raw = PARSERS[engine](clipped);
  let warning: string | null = null;
  if (!raw.length && clipped.trim()) {
    for (const id of ENGINE_IDS) {
      if (id === engine) continue;
      const alt = PARSERS[id](clipped);
      if (alt.length) {
        used = id;
        raw = alt;
        warning = `Nothing parsed as ${ENGINES[engine].name}; this looks like ${ENGINES[id].name} output, so it was normalized as ${ENGINES[id].name}.`;
        break;
      }
    }
    if (!raw.length) {
      warning = `No findings recognized. Expected ${PASTE_FORMAT[engine]}. An unparsed paste is not a clean result.`;
    }
  }
  const findings = finalizeFindings(raw);
  return {
    ok: true,
    engine: used,
    requested_engine: engine,
    detected: used !== engine,
    findings,
    severity_counts: severityCounts(findings),
    warning,
  };
}
