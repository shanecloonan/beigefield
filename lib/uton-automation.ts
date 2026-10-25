import type { PathSource } from "@/lib/uton-path";

/** Control-flow listings for the path. The strings are not executed. */
export const automationSource = {
  afterBurn1: {
    file: "automation/after-burn-1.ts",
    code: `// Listing only. Send broadcasts the names this returns once bounce is in the trace.

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
    code: `// After on_bounce. Names the next wallet message. Send broadcasts that message.

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

export type LaterStep = "burn-2" | "redeem-notification" | "withdraw";

export type AutomationStep =
  | "burn-1"
  | "burn-notification"
  | "bounce"
  | LaterStep;

export type LaterDraftId = "redeem-burn" | "redeem-notify" | "withdraw";

/**
 * The path already contains the bounce, so afterBurn1 queues the later
 * wallet messages. Send broadcasts that queue.
 */
export const afterBurn1Trace = [
  "burn-1",
  "burn-notification",
  "bounce",
] as const satisfies readonly AutomationStep[];

export function watchBounce(trace: readonly AutomationStep[]): "wait-bounce" | "queued" {
  let phase: "wait-bounce" | "queued" = "wait-bounce";
  for (const step of trace) {
    if (phase === "wait-bounce" && step === "bounce") phase = "queued";
  }
  return phase;
}

export function afterBurn1(trace: readonly AutomationStep[]): readonly LaterStep[] {
  if (watchBounce(trace) !== "queued") return [];
  return ["burn-2", "redeem-notification", "withdraw"];
}

export function nextAfter(prior: "bounce" | LaterStep): LaterStep | undefined {
  if (prior === "bounce") return "burn-2";
  if (prior === "burn-2") return "redeem-notification";
  if (prior === "redeem-notification") return "withdraw";
  return undefined;
}

export function laterDraftId(step: LaterStep): LaterDraftId {
  if (step === "burn-2") return "redeem-burn";
  if (step === "redeem-notification") return "redeem-notify";
  return "withdraw";
}
