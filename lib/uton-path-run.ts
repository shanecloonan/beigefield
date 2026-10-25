import { Address } from "@ton/core";
import { FUNDED_WALLET_ADDRESS } from "@/lib/funded-wallet-public";
import {
  compileStep,
  outgoingRequest,
  type BodyField,
  type MainnetScriptRequest,
  type OutgoingMessage,
  type ScriptStep,
  type StepErrors,
} from "@/lib/ton-message";
import { utonMinter } from "@/lib/uton";
import { compileMinterQuery } from "@/lib/uton-query";

/** TON attached for gas. The uTON amount is a separate field, in nanotons. */
export const PATH_GAS_TON = {
  burn: "0.2",
  notify: "0.15",
  "redeem-burn": "0.2",
  "redeem-notify": "0.15",
  withdraw: "0.5",
} as const;

/** 1 uTON. Run path burns this amount on proxy id 3 and again on the listed proxy. */
export const PATH_UTON_NANO = "1000000000";

export type PathDefaultsInput = {
  owner: string;
  jettonWallet?: string;
  proxyId?: string;
  previousOwner?: string;
  previousJetton?: string;
  previousProxy?: string;
};

const addressFields = new Set(["response", "owner", "recipient"]);

/** The wallet the path is filled for. A connected mainnet wallet wins. Otherwise the desk wallet. */
export function pathOwner(input: {
  localWallet: boolean;
  onMainnet: boolean;
  address?: string;
}): string {
  if (!input.localWallet && input.onMainnet && input.address?.trim()) return input.address.trim();
  return FUNDED_WALLET_ADDRESS;
}

export function applyPathDefaults(
  steps: readonly ScriptStep[],
  input: PathDefaultsInput,
): ScriptStep[] {
  return steps.map((step) => fillStep(step, input));
}

export type PathRunOk = {
  ok: true;
  batches: MainnetScriptRequest[];
  summary: string;
  skipped: string[];
  firstAddress: string;
};

export type PathRunResult = PathRunOk | { ok: false; message: string };

export function compilePathRun(
  steps: {
    burn: ScriptStep;
    notify: ScriptStep;
    redeemBurn: ScriptStep;
    redeemNotify: ScriptStep;
    withdraw: ScriptStep;
  },
  options?: { fromRaw?: string; nowSeconds?: number; maxMessages?: number },
): PathRunResult {
  const burn = compileStep(steps.burn);
  if (!burn.ok) return { ok: false, message: burnFailure(burn.errors) };
  const notify = compileStep(steps.notify);
  if (!notify.ok) return { ok: false, message: notifyFailure(notify.errors) };

  const messages: OutgoingMessage[] = [burn.message, notify.message];
  const names = ["burn", "burn notification"];
  const skipped: string[] = [];

  const redeemBurn = compileStep(steps.redeemBurn);
  const redeemNotify = compileStep(steps.redeemNotify);
  if (redeemBurn.ok && redeemNotify.ok) {
    messages.push(redeemBurn.message, redeemNotify.message);
    names.push("redeem burn", "redeem notification");
  } else {
    skipped.push(
      "The redeem burn and redeem notification were not included. They need a proxy id the minter lists. Proxy id 3 is only the first burn, and that id is not listed, so its notification bounces.",
    );
  }

  const withdraw = compileStep(steps.withdraw);
  if (withdraw.ok) {
    messages.push(withdraw.message);
    names.push("withdraw");
  } else {
    skipped.push(
      "The withdraw was not included. Its destination is the pending withdraw contract, created after a listed burn is accepted, then held for the time lock. It is not your jetton wallet.",
    );
  }

  const query = compileMinterQuery(steps.withdraw);
  if (query.ok) {
    messages.push(query.message);
    names.push("minter query");
  } else {
    skipped.push(
      "The minter query was not included. It is opcode 0x1001 to the minter, built from the withdraw's query id, recipient, response, and attached TON.",
    );
  }

  const limit = options?.maxMessages && options.maxMessages >= 1 ? options.maxMessages : 4;
  const batches: MainnetScriptRequest[] = [];
  for (let index = 0; index < messages.length; index += limit) {
    batches.push(
      outgoingRequest(messages.slice(index, index + limit), {
        fromRaw: options?.fromRaw,
        nowSeconds: options?.nowSeconds,
      }),
    );
  }

  const firstAddress = messages[0]?.address ?? "";
  return {
    ok: true,
    batches,
    summary: `Sent the path on mainnet. ${joinNames(names)}.`,
    skipped,
    firstAddress,
  };
}

function fillStep(step: ScriptStep, input: PathDefaultsInput): ScriptStep {
  let next = step;
  const gas = PATH_GAS_TON[step.id as keyof typeof PATH_GAS_TON];
  if (gas && !next.amount.trim()) next = { ...next, amount: gas };

  if (step.id === "burn" || step.id === "redeem-burn") {
    const destination = takeJetton(next.destination, input.jettonWallet, input.previousJetton);
    if (destination !== next.destination) next = { ...next, destination };
  }
  if ((step.id === "notify" || step.id === "redeem-notify") && !next.destination.trim()) {
    next = { ...next, destination: utonMinter };
  }

  if (next.body.kind !== "fields") return next;
  const fields = next.body.fields.map((field) => fillField(step.id, field, input));
  return { ...next, body: { ...next.body, fields } };
}

function fillField(stepId: string, field: BodyField, input: PathDefaultsInput): BodyField {
  if (addressFields.has(field.id) && field.kind === "address") {
    const value = takeAddress(field.value, input.owner, input.previousOwner);
    return value === field.value ? field : { ...field, value };
  }
  if (field.id === "amount" && field.kind === "coins" && !field.value.trim()) {
    if (stepId === "withdraw") return field;
    return { ...field, value: PATH_UTON_NANO };
  }
  if (
    field.id === "proxy_id" &&
    field.kind === "uint" &&
    (stepId === "redeem-burn" || stepId === "redeem-notify") &&
    input.proxyId &&
    blankOrPrevious(field.value, input.previousProxy)
  ) {
    return { ...field, value: input.proxyId };
  }
  return field;
}

function takeJetton(current: string, next: string | undefined, previous: string | undefined): string {
  if (!next || sameAddress(next, utonMinter)) return current;
  if (current.trim() && sameAddress(current, utonMinter)) return next;
  return takeAddress(current, next, previous);
}

function takeAddress(current: string, next: string | undefined, previous: string | undefined): string {
  if (!next) return current;
  if (!current.trim()) return next;
  if (previous && sameAddress(current, previous)) return next;
  if (
    !previous &&
    sameAddress(current, FUNDED_WALLET_ADDRESS) &&
    !sameAddress(next, FUNDED_WALLET_ADDRESS)
  ) {
    return next;
  }
  return current;
}

function blankOrPrevious(current: string, previous: string | undefined): boolean {
  if (!current.trim()) return true;
  return previous !== undefined && current.trim() === previous.trim();
}

function sameAddress(left: string, right: string): boolean {
  try {
    return Address.parse(left).equals(Address.parse(right));
  } catch {
    return false;
  }
}

function burnFailure(errors: StepErrors): string {
  if (errors.destination) {
    return "Nothing was sent. The uTON jetton wallet is still empty. That address holds your uTON. The minter calculates it from the wallet you connect, or from the funded desk wallet. It is not that wallet, and it is not the minter. Connect a mainnet wallet or use the funded wallet, then run the path again.";
  }
  if (errors.amount) return "Nothing was sent. Enter the TON attached on the burn. It pays gas.";
  if (errors.fields?.amount) {
    return "Nothing was sent. Enter how many uTON to burn, in nanotons. 1000000000 is 1 uTON.";
  }
  return "Nothing was sent. Complete the burn, then run the path again.";
}

function notifyFailure(errors: StepErrors): string {
  if (errors.destination) return "Nothing was sent. The burn notification goes to the minter.";
  if (errors.amount) return "Nothing was sent. Enter the TON attached on the burn notification. It pays the minter.";
  if (errors.fields?.amount) {
    return "Nothing was sent. Enter the uTON amount on the burn notification, in nanotons. 1000000000 is 1 uTON.";
  }
  return "Nothing was sent. Complete the burn notification, then run the path again.";
}

function joinNames(names: string[]): string {
  const [first, ...rest] = names;
  const head = first ? first.charAt(0).toUpperCase() + first.slice(1) : "";
  if (rest.length === 0) return head;
  if (rest.length === 1) return `${head} and ${rest[0]}`;
  return `${head}, ${rest.slice(0, -1).join(", ")}, and ${rest[rest.length - 1]}`;
}
