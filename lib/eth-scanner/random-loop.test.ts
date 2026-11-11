import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  DEFAULT_LOOP_GAP_MS,
  MIN_LOOP_GAP_MS,
  RANDOM_HISTORY_CAP,
  clampLoopGapMs,
  isEtherscanRateLimit,
  pushCapped,
  runContinuousRandom,
} from "./random-loop";

const ADDR_A = "0x" + "aa".repeat(20);
const ADDR_B = "0x" + "bb".repeat(20);

describe("clampLoopGapMs", () => {
  it("keeps a few-second default and refuses a zero gap", () => {
    assert.equal(clampLoopGapMs(8_000), 8_000);
    assert.equal(clampLoopGapMs(0), MIN_LOOP_GAP_MS);
    assert.equal(clampLoopGapMs(1), MIN_LOOP_GAP_MS);
    assert.equal(clampLoopGapMs(Number.NaN), DEFAULT_LOOP_GAP_MS);
    assert.equal(clampLoopGapMs(999_999), 120_000);
  });
});

describe("isEtherscanRateLimit", () => {
  it("matches free-tier and community-pool wording, including the Lane A note", () => {
    assert.equal(isEtherscanRateLimit("Max rate limit reached"), true);
    assert.equal(isEtherscanRateLimit("Community Free API limit reached. Resets tomorrow."), true);
    assert.equal(isEtherscanRateLimit("etherscan rate-limited after retries"), true);
    assert.equal(isEtherscanRateLimit("Contract source code not verified"), false);
  });
});

describe("pushCapped", () => {
  it("keeps the newest rows and drops the tail", () => {
    const rows = pushCapped([1, 2, 3], 4, 3);
    assert.deepEqual(rows, [4, 1, 2]);
    assert.equal(RANDOM_HISTORY_CAP >= 1, true);
  });
});

describe("runContinuousRandom", () => {
  it("scans one contract, waits the full gap, then scans the next", async () => {
    let n = 0;
    const events: string[] = [];
    const addresses = [ADDR_A, ADDR_B, ADDR_A];
    const result = await runContinuousRandom({
      gapMs: 5_000,
      stop: () => n >= 2,
      sample: async () => {
        events.push("sample");
        return { ok: true, address: addresses[n] || ADDR_A };
      },
      scan: async (address) => {
        events.push(`scan:${address}`);
        n += 1;
        return { ok: true };
      },
      sleep: async (ms) => {
        events.push(`sleep:${ms}`);
      },
    });
    assert.equal(n, 2);
    assert.equal(result.reason, "stopped");
    assert.equal(result.scanned, 2);
    assert.deepEqual(events, [
      "sample",
      `scan:${ADDR_A}`,
      ...Array.from({ length: 5_000 / 250 }, () => "sleep:250"),
      "sample",
      `scan:${ADDR_B}`,
    ]);
    const slept = events.filter((e) => e.startsWith("sleep:")).reduce((sum, e) => sum + Number(e.slice(6)), 0);
    assert.equal(slept, 5_000);
  });

  it("stops during the gap and does not sample again", async () => {
    let samples = 0;
    let scans = 0;
    let slept = 0;
    const stop = { current: false };
    const result = await runContinuousRandom({
      gapMs: 5_000,
      stop: () => stop.current,
      sample: async () => {
        samples += 1;
        return { ok: true, address: ADDR_A };
      },
      scan: async () => {
        scans += 1;
        return { ok: true };
      },
      sleep: async (ms) => {
        slept += ms;
        if (slept >= 1_000) stop.current = true;
      },
    });
    assert.equal(samples, 1);
    assert.equal(scans, 1);
    assert.equal(result.reason, "stopped");
    assert.equal(result.scanned, 1);
    assert.ok(slept >= 1_000);
    assert.ok(slept < 5_000);
  });

  it("pauses on a rate-limit sample and does not scan that pick", async () => {
    let step = 0;
    let scans = 0;
    const result = await runContinuousRandom({
      gapMs: 5_000,
      stop: () => false,
      sample: async () => {
        step += 1;
        if (step === 2) return { ok: false, kind: "rate_limit", error: "Community Free API limit reached" };
        return { ok: true, address: ADDR_A };
      },
      scan: async () => {
        scans += 1;
        return { ok: true };
      },
      sleep: async () => {},
    });
    assert.equal(scans, 1);
    assert.equal(result.reason, "rate_limit");
    assert.match(result.message, /Community Free API limit/);
    assert.equal(result.scanned, 1);
  });

  it("pauses when the scan itself was rate-limited", async () => {
    let scans = 0;
    const result = await runContinuousRandom({
      gapMs: 8_000,
      stop: () => false,
      sample: async () => ({ ok: true, address: ADDR_A }),
      scan: async () => {
        scans += 1;
        return { ok: true, rateLimited: true, error: "etherscan rate-limited after retries" };
      },
      sleep: async () => {
        throw new Error("gap should not run after a rate limit");
      },
    });
    assert.equal(scans, 1);
    assert.equal(result.reason, "rate_limit");
    assert.equal(result.scanned, 1);
  });

  it("raises a too-small gap to the minimum before sleeping", async () => {
    let n = 0;
    let slept = 0;
    await runContinuousRandom({
      gapMs: () => 100,
      stop: () => n >= 2,
      sample: async () => ({ ok: true, address: ADDR_A }),
      scan: async () => {
        n += 1;
        return { ok: true };
      },
      sleep: async (ms) => {
        slept += ms;
      },
    });
    assert.equal(slept, MIN_LOOP_GAP_MS);
  });

  it("waits before retrying a block that had no verified contract", async () => {
    let samples = 0;
    let slept = 0;
    await runContinuousRandom({
      gapMs: 5_000,
      stop: () => samples >= 2,
      sample: async () => {
        samples += 1;
        if (samples === 1) return { ok: false, kind: "retry", error: "No verified contract in the sampled blocks." };
        return { ok: true, address: ADDR_B };
      },
      scan: async () => ({ ok: true }),
      sleep: async (ms) => {
        slept += ms;
      },
    });
    assert.equal(samples, 2);
    assert.equal(slept, 5_000);
  });
});
