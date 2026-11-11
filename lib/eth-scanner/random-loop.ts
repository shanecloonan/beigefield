/**
 * Pace a /test continuous Lane A run. One sample + one scan, then a gap,
 * until the caller stops or Etherscan rate-limits. The gap is what keeps a
 * fast scan from chaining straight into the next sample on the free tier
 * (~3 calls/second, ~100,000/day).
 */

export const DEFAULT_LOOP_GAP_MS = 8_000;
export const MIN_LOOP_GAP_MS = 5_000;
export const MAX_LOOP_GAP_MS = 120_000;
export const RANDOM_HISTORY_CAP = 20;
export const SESSION_ROW_CAP = 40;
const WAIT_SLICE_MS = 250;

const RATE_RE =
  /rate limit|rate-limit|max rate|too many requests|max calls per|rate limiter|community free api limit|daily limit reached/i;

export function clampLoopGapMs(raw: number): number {
  if (!Number.isFinite(raw)) return DEFAULT_LOOP_GAP_MS;
  return Math.min(MAX_LOOP_GAP_MS, Math.max(MIN_LOOP_GAP_MS, Math.round(raw)));
}

export function isEtherscanRateLimit(text: string | null | undefined): boolean {
  return RATE_RE.test(text || "");
}

export function pushCapped<T>(prev: readonly T[], row: T, cap: number): T[] {
  const n = Number.isFinite(cap) && cap >= 1 ? Math.floor(cap) : 1;
  return [row, ...prev].slice(0, n);
}

export type RandomLoopSample =
  | { ok: true; address: string }
  | { ok: false; kind: "rate_limit" | "retry" | "pause"; error: string };

export type RandomLoopScan = {
  ok: boolean;
  rateLimited?: boolean;
  error?: string;
};

export type ContinuousRandomResult = {
  scanned: number;
  reason: "stopped" | "rate_limit" | "paused";
  message: string;
};

export type ContinuousRandomOpts = {
  /** Milliseconds, or a reader so the UI can change the gap while a scan is in flight. */
  gapMs: number | (() => number);
  stop: () => boolean;
  sample: () => Promise<RandomLoopSample>;
  scan: (address: string) => Promise<RandomLoopScan>;
  sleep: (ms: number) => Promise<void>;
  onScanned?: (info: { address: string; index: number }) => void;
  onWaitTick?: (remainingMs: number) => void;
};

function readGap(gapMs: number | (() => number)): number {
  const raw = typeof gapMs === "function" ? gapMs() : gapMs;
  return clampLoopGapMs(raw);
}

async function waitGap(
  ms: number,
  stop: () => boolean,
  sleep: (ms: number) => Promise<void>,
  onTick?: (remainingMs: number) => void,
): Promise<"slept" | "stopped"> {
  let left = ms;
  while (left > 0) {
    if (stop()) return "stopped";
    onTick?.(left);
    const step = Math.min(WAIT_SLICE_MS, left);
    await sleep(step);
    left -= step;
  }
  return stop() ? "stopped" : "slept";
}

function stoppedMessage(scanned: number): string {
  const noun = scanned === 1 ? "scan" : "scans";
  return `Stopped after ${scanned} ${noun}. No further scan will start until you press Start.`;
}

export async function runContinuousRandom(opts: ContinuousRandomOpts): Promise<ContinuousRandomResult> {
  let scanned = 0;
  while (!opts.stop()) {
    const picked = await opts.sample();
    if (opts.stop()) {
      return { scanned, reason: "stopped", message: stoppedMessage(scanned) };
    }
    if (!picked.ok) {
      if (picked.kind === "retry") {
        const waited = await waitGap(readGap(opts.gapMs), opts.stop, opts.sleep, opts.onWaitTick);
        if (waited === "stopped") return { scanned, reason: "stopped", message: stoppedMessage(scanned) };
        continue;
      }
      const reason = picked.kind === "rate_limit" ? "rate_limit" : "paused";
      return { scanned, reason, message: picked.error };
    }
    if (opts.stop()) {
      return { scanned, reason: "stopped", message: stoppedMessage(scanned) };
    }
    const ran = await opts.scan(picked.address);
    if (ran.ok) {
      scanned += 1;
      opts.onScanned?.({ address: picked.address, index: scanned });
    }
    if (ran.rateLimited) {
      return {
        scanned,
        reason: "rate_limit",
        message: ran.error || "Etherscan rate limit reached. Paused so the loop does not keep calling.",
      };
    }
    if (!ran.ok) {
      return { scanned, reason: "paused", message: ran.error || "The scan failed. Paused." };
    }
    if (opts.stop()) {
      return { scanned, reason: "stopped", message: stoppedMessage(scanned) };
    }
    const waited = await waitGap(readGap(opts.gapMs), opts.stop, opts.sleep, opts.onWaitTick);
    if (waited === "stopped") {
      return { scanned, reason: "stopped", message: stoppedMessage(scanned) };
    }
  }
  return { scanned, reason: "stopped", message: stoppedMessage(scanned) };
}
