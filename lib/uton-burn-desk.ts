/**
 * Desk-wallet burn that redeems TON.
 * Same steps as Run path on /tons: proxy id 3 burn and notification, then the
 * listed-proxy redeem burn and notification, then the minter query. The
 * withdraw stays out until its contract exists. Signing stays on /api/ton/send.
 */
import { FUNDED_WALLET_ADDRESS, FUNDED_WALLET_MAX_MESSAGES } from "./funded-wallet-public";
import type { MainnetScriptRequest, ScriptStep } from "./ton-message";
import { utonMinter } from "./uton";
import {
  applyPathDefaults,
  compilePathRun,
  PATH_GAS_TON,
  type PathRunResult,
} from "./uton-path-run";
import { utonTemplateBody, utonTemplateById, type UtonTemplateId } from "./uton-templates";

const UTON_SCALE = BigInt("1000000000");

/** Pause between funded batches so the sequence number can move before the next send. */
export const DESK_BURN_BATCH_GAP_MS = 5000;

export function parseUtonAmount(
  input: string,
): { ok: true; nanotons: string } | { ok: false; message: string } {
  const trimmed = input.trim();
  if (!trimmed) {
    return { ok: false, message: "Enter how many uTON to burn." };
  }
  if (!/^\d+(\.\d{1,9})?$/.test(trimmed)) {
    return {
      ok: false,
      message: "Enter a uTON amount with up to 9 decimal places.",
    };
  }
  const [whole, frac = ""] = trimmed.split(".");
  const nanotons = BigInt(whole) * UTON_SCALE + BigInt((frac.padEnd(9, "0") || "0"));
  if (nanotons <= BigInt(0)) {
    return { ok: false, message: "Enter an amount of uTON greater than zero." };
  }
  return { ok: true, nanotons: nanotons.toString() };
}

export type DeskBurnSteps = {
  burn: ScriptStep;
  notify: ScriptStep;
  redeemBurn: ScriptStep;
  redeemNotify: ScriptStep;
  withdraw: ScriptStep;
};

export function deskBurnPathSteps(nanotons: string): DeskBurnSteps {
  return {
    burn: burnDraft("burn", nanotons),
    notify: notificationDraft("notify", nanotons),
    redeemBurn: withProxy(burnDraft("redeem-burn", nanotons), ""),
    redeemNotify: withProxy(notificationDraft("redeem-notify", nanotons), ""),
    withdraw: withdrawDraft("withdraw"),
  };
}

export type PathDefaultsRead =
  | { ok: true; jettonWallet: string; proxyId?: string }
  | { ok: false; message: string };

export function readPathDefaultsPayload(payload: unknown): PathDefaultsRead | null {
  if (!payload || typeof payload !== "object" || !("ok" in payload)) return null;
  if (payload.ok === true && "jettonWallet" in payload && typeof payload.jettonWallet === "string") {
    const proxyId =
      "proxyId" in payload && typeof payload.proxyId === "string" ? payload.proxyId : undefined;
    return { ok: true, jettonWallet: payload.jettonWallet, proxyId };
  }
  if (payload.ok === false && "message" in payload && typeof payload.message === "string") {
    return { ok: false, message: payload.message };
  }
  return null;
}

export function deskLookupNote(read: PathDefaultsRead | null): string {
  if (!read) return "The lookup did not answer. Submit tries again.";
  if (!read.ok) return read.message;
  if (!read.proxyId) {
    return `uTON wallet ${read.jettonWallet}. The minter did not return a listed proxy, so a burn from this page would not redeem.`;
  }
  return `uTON wallet ${read.jettonWallet}. Listed proxy ${read.proxyId}.`;
}

export type DeskBurnRun =
  | { ok: true; text: string; href: string }
  | { ok: false; text: string };

export async function runDeskBurn(input: {
  amountLabel: string;
  nanotons: string;
  jettonWallet?: string;
  proxyId?: string;
  fromRaw: string;
  nowSeconds?: number;
  send: (request: MainnetScriptRequest) => Promise<{ ok: true } | { ok: false; text: string }>;
  sleep?: (ms: number) => Promise<void>;
  onBatch?: (index: number, total: number) => void;
}): Promise<DeskBurnRun> {
  const compiled = compileDeskBurn({
    nanotons: input.nanotons,
    jettonWallet: input.jettonWallet,
    proxyId: input.proxyId,
    fromRaw: input.fromRaw,
    nowSeconds: input.nowSeconds,
  });
  if (!compiled.ok) return { ok: false, text: compiled.message };

  const sleep = input.sleep ?? wait;
  for (let index = 0; index < compiled.batches.length; index += 1) {
    const batch = compiled.batches[index];
    if (!batch) continue;
    input.onBatch?.(index, compiled.batches.length);
    const result = await input.send(batch);
    if (!result.ok) {
      const lead = index > 0 ? "The first part of the path was sent. The rest was not. " : "";
      return { ok: false, text: `${lead}${result.text}` };
    }
    if (index < compiled.batches.length - 1) await sleep(DESK_BURN_BATCH_GAP_MS);
  }

  return {
    ok: true,
    text: deskBurnSuccess(input.amountLabel, compiled),
    href: `https://tonviewer.com/${encodeURIComponent(compiled.firstAddress)}`,
  };
}

export function compileDeskBurn(input: {
  nanotons: string;
  jettonWallet?: string;
  proxyId?: string;
  fromRaw: string;
  nowSeconds?: number;
}): PathRunResult {
  const steps = deskBurnPathSteps(input.nanotons);
  const filled = applyPathDefaults(
    [steps.burn, steps.notify, steps.redeemBurn, steps.redeemNotify, steps.withdraw],
    {
      owner: FUNDED_WALLET_ADDRESS,
      jettonWallet: input.jettonWallet,
      proxyId: input.proxyId,
    },
  );
  const byId = Object.fromEntries(filled.map((step) => [step.id, step]));
  const compiled = compilePathRun(
    {
      burn: byId.burn ?? steps.burn,
      notify: byId.notify ?? steps.notify,
      redeemBurn: byId["redeem-burn"] ?? steps.redeemBurn,
      redeemNotify: byId["redeem-notify"] ?? steps.redeemNotify,
      withdraw: byId.withdraw ?? steps.withdraw,
    },
    {
      fromRaw: input.fromRaw,
      nowSeconds: input.nowSeconds,
      maxMessages: FUNDED_WALLET_MAX_MESSAGES,
    },
  );
  if (!compiled.ok) return compiled;
  if (!compiled.summary.includes("redeem burn")) {
    return {
      ok: false,
      message:
        "Nothing was sent. The redeem needs a proxy id the minter lists, and this page sends only when that redeem is included.",
    };
  }
  return compiled;
}

function deskBurnSuccess(amount: string, compiled: Extract<PathRunResult, { ok: true }>): string {
  return [`Burned ${amount.trim()} uTON from the desk wallet.`, compiled.summary, ...compiled.skipped]
    .filter((part) => part.trim().length > 0)
    .join(" ");
}

function burnDraft(id: string, nanotons: string): ScriptStep {
  return templateDraft(id, "uton-burn", {
    destination: "",
    amount: PATH_GAS_TON.burn,
    fields: { response: FUNDED_WALLET_ADDRESS, amount: nanotons },
  });
}

function notificationDraft(id: string, nanotons: string): ScriptStep {
  return templateDraft(id, "burn-notification", {
    destination: utonMinter,
    amount: PATH_GAS_TON.notify,
    fields: {
      owner: FUNDED_WALLET_ADDRESS,
      response: FUNDED_WALLET_ADDRESS,
      amount: nanotons,
    },
  });
}

function withdrawDraft(id: string): ScriptStep {
  return templateDraft(id, "withdraw", {
    destination: "",
    amount: PATH_GAS_TON.withdraw,
    fields: {
      recipient: FUNDED_WALLET_ADDRESS,
      response: FUNDED_WALLET_ADDRESS,
    },
  });
}

function templateDraft(
  id: string,
  templateId: UtonTemplateId,
  patch: { destination: string; amount: string; fields: Record<string, string> },
): ScriptStep {
  const template = utonTemplateById(templateId);
  if (!template) throw new Error(`Missing template ${templateId}.`);
  const body = utonTemplateBody(template);
  return {
    id,
    destination: patch.destination,
    amount: patch.amount,
    unit: "ton",
    bounceable: template.bounceable,
    body: {
      ...body,
      fields: body.fields.map((field) =>
        patch.fields[field.id] !== undefined ? { ...field, value: patch.fields[field.id] ?? "" } : field,
      ),
    },
  };
}

function withProxy(step: ScriptStep, proxy: string): ScriptStep {
  if (step.body.kind !== "fields") return step;
  return {
    ...step,
    body: {
      ...step.body,
      fields: step.body.fields.map((field) =>
        field.id === "proxy_id" ? { ...field, value: proxy } : field,
      ),
    },
  };
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
