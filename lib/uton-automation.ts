import type { PathSource } from "@/lib/uton-path";

/** Control-flow listings for the path. Strings only — nothing here is called. */
export const automationSource = {
  afterBurn1: {
    file: "automation/after-burn-1.ts",
    code: `// Listing only. The page does not call this, and it does not broadcast.

type Later = "burn-2" | "redeem-notification" | "withdraw";

type Step =
  | "burn-1"
  | "burn-notification"
  | "bounce"
  | Later;

type Phase = "wait-bounce" | "queued";

function watchBounce(trace: readonly Step[]): Phase {
  let phase: Phase = "wait-bounce";
  for (const step of trace) {
    if (phase === "wait-bounce" && step === "bounce") phase = "queued";
  }
  return phase;
}

function afterBurn1(trace: readonly Step[]): readonly Later[] {
  if (watchBounce(trace) !== "queued") return [];
  return ["burn-2", "redeem-notification", "withdraw"];
}
`,
  },
  queueAfterBounce: {
    file: "automation/queue-after-bounce.ts",
    code: `// After on_bounce. Names the rest of the path. Not sent.

type Later = "burn-2" | "redeem-notification" | "withdraw";

function nextAfter(prior: "bounce" | Later): Later | undefined {
  if (prior === "bounce") return "burn-2";
  if (prior === "burn-2") return "redeem-notification";
  if (prior === "redeem-notification") return "withdraw";
  return undefined;
}
`,
  },
} as const satisfies Record<string, PathSource>;
