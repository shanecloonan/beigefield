/**
 * Spawn `python -m eth_scanner blend`. Defensive only.
 * Etherscan keys are whatever the process already has. This module never
 * injects a fallback key.
 */

import { spawn } from "node:child_process";
import path from "node:path";
import { listPythonCandidates, pythonHomeFor } from "./python-runtime";

const DEFAULT_TIMEOUT_MS = 120_000;

export type BlendRun = {
  ok: boolean;
  data?: unknown;
  error?: string;
};

function runOnce(
  bin: string,
  source: Parameters<typeof pythonHomeFor>[0],
  args: string[],
  timeoutMs: number,
): Promise<{ code: number | null; stdout: string; stderr: string }> {
  const root = process.cwd();
  const home = pythonHomeFor(source, bin);
  return new Promise((resolve) => {
    const child = spawn(bin, ["-m", "eth_scanner", "blend", ...args], {
      cwd: path.join(root, "eth-scanner"),
      env: {
        ...process.env,
        PYTHONPATH: path.join(root, "eth-scanner", "src"),
        ...(home ? { PYTHONHOME: home } : {}),
      },
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
    }, timeoutMs);
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr });
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ code: null, stdout, stderr: err.message });
    });
  });
}

export async function runBlendCli(args: string[], timeoutMs = DEFAULT_TIMEOUT_MS): Promise<BlendRun> {
  const candidates = listPythonCandidates();
  if (!candidates.length) {
    return { ok: false, error: "Python is not available, so Blend could not run." };
  }
  let last = "Blend did not start.";
  for (const cand of candidates) {
    const ran = await runOnce(cand.bin, cand.source, args, timeoutMs);
    if (ran.code === 0) {
      try {
        return { ok: true, data: JSON.parse(ran.stdout) };
      } catch {
        return { ok: false, error: "Blend returned a response that was not JSON." };
      }
    }
    const detail = (ran.stderr || ran.stdout || `exit ${ran.code}`).replace(/\s+/g, " ").trim();
    last = detail.slice(0, 400);
  }
  return { ok: false, error: last };
}

export function blendRandomEnabled(): boolean {
  return ["1", "true", "yes", "on"].includes((process.env.ETH_SCANNER_BLEND_RANDOM || "").trim().toLowerCase());
}

/** Env key only. The /test free-tier fallback is not used here. */
export function blendEtherscanKeys(): string {
  return (process.env.ETHERSCAN_API_KEYS || "").trim();
}
