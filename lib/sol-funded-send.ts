/**
 * Signs one Katana user transaction with the desk wallet and broadcasts it
 * on Solana mainnet. Do not import this file from a client component.
 */
import { Connection, Transaction, type TransactionInstruction } from "@solana/web3.js";
import {
  authorizedLookupFromSnapshot,
  buildAuthorizedInstantWithdraw,
  snapshotFromAuthorizedLookup,
} from "@/lib/katana-authorized";
import { compilePathRun, type KatanaSendResult } from "@/lib/katana-path-run";
import { buildKatanaInstructions } from "@/lib/katana-ix";
import { parseSolPubkey } from "@/lib/katana-accounts";
import { loadKatanaSnapshot, solanaRpc, type KatanaSnapshotResult } from "@/lib/katana-query";
import type { KatanaSnapshot } from "@/lib/katana-accounts";
import { isKatanaAction, katanaVault, readBaseUnits, type KatanaAction } from "@/lib/katana";
import { SolFundedKeyError, openSolFundedWallet } from "@/lib/sol-funded-wallet";

const UNCONFIRMED =
  "The network did not confirm the transaction. Check the account before trying again, so it is not sent twice.";
const REJECTED_READ = "The message could not be read. Nothing was sent.";
const SENDER_MISMATCH = "This desk sends only from its own wallet. Nothing was sent.";

export type SolExecuteArgs = {
  instructions: TransactionInstruction[];
  feePayer: string;
};

export type SolExecuteResult = { signature: string };

export type SolSendDeps = {
  deskAddress?: () => string | Promise<string>;
  load?: (input: { owner: string; state: string }) => Promise<KatanaSnapshotResult>;
  execute?: (args: SolExecuteArgs) => Promise<SolExecuteResult>;
  rpc?: string;
};

type Parsed =
  | { ok: true; sender: string; state: string; action: KatanaAction; amount?: bigint }
  | { ok: false; kind: "rejected"; message: string };

function parseRequest(input: unknown): Parsed {
  if (!input || typeof input !== "object") {
    return { ok: false, kind: "rejected", message: REJECTED_READ };
  }
  const record = input as Record<string, unknown>;
  if (typeof record.sender !== "string" || typeof record.state !== "string") {
    return { ok: false, kind: "rejected", message: REJECTED_READ };
  }
  if (!isKatanaAction(record.action)) {
    return {
      ok: false,
      kind: "rejected",
      message: "The instruction is not a remaining Katana action. Nothing was sent.",
    };
  }
  if (!katanaVault(record.state)) {
    return {
      ok: false,
      kind: "rejected",
      message: "This path executes only a listed Katana vault. Nothing was sent.",
    };
  }
  const compiled = compilePathRun({
    sender: record.sender,
    state: record.state,
    action: record.action,
    amount: typeof record.amount === "string" ? record.amount : record.amount === undefined ? undefined : String(record.amount),
  });
  if (!compiled.ok) return { ok: false, kind: "rejected", message: compiled.message };
  let amount: bigint | undefined;
  if (compiled.amount) {
    const parsed = readBaseUnits(compiled.amount);
    if (parsed === null) {
      return { ok: false, kind: "rejected", message: "The instant withdraw amount is missing. Nothing was sent." };
    }
    amount = parsed;
  }
  return { ok: true, sender: compiled.sender, state: compiled.state, action: compiled.action, amount };
}

type AuthorizedParsed =
  | {
      ok: true;
      sender: string;
      state: string;
      userAuthority: string;
      destination: string;
      amount: string;
    }
  | { ok: false; kind: "rejected"; message: string };

function parseAuthorizedRequest(input: unknown): AuthorizedParsed {
  if (!input || typeof input !== "object") {
    return { ok: false, kind: "rejected", message: REJECTED_READ };
  }
  const record = input as Record<string, unknown>;
  if (typeof record.sender !== "string" || typeof record.state !== "string") {
    return { ok: false, kind: "rejected", message: REJECTED_READ };
  }
  if (typeof record.userAuthority !== "string" || typeof record.destination !== "string") {
    return { ok: false, kind: "rejected", message: REJECTED_READ };
  }
  if (!katanaVault(record.state)) {
    return {
      ok: false,
      kind: "rejected",
      message: "This path executes only a listed Katana vault. Nothing was sent.",
    };
  }
  const amount =
    typeof record.amount === "string"
      ? record.amount
      : record.amount === undefined
        ? ""
        : String(record.amount);
  return {
    ok: true,
    sender: record.sender.trim(),
    state: record.state.trim(),
    userAuthority: record.userAuthority.trim(),
    destination: record.destination.trim(),
    amount,
  };
}

export async function sendAuthorizedInstantWithdraw(
  input: unknown,
  deps: SolSendDeps = {},
): Promise<KatanaSendResult> {
  const parsed = parseAuthorizedRequest(input);
  if (!parsed.ok) return parsed;

  let desk: string;
  try {
    desk = deps.deskAddress ? await deps.deskAddress() : openSolFundedWallet().address;
  } catch (error) {
    if (error instanceof SolFundedKeyError) {
      return { ok: false, kind: "rejected", message: error.message };
    }
    return { ok: false, kind: "rejected", message: "The desk key could not be read. Nothing was sent." };
  }

  if (parsed.sender !== desk) {
    return { ok: false, kind: "rejected", message: SENDER_MISMATCH };
  }

  const loaded = await (deps.load ?? ((args: { owner: string; state: string }) => loadKatanaSnapshot(args, { rpc: deps.rpc })))({
    owner: parsed.userAuthority,
    state: parsed.state,
  });
  if (!loaded.ok) {
    return { ok: false, kind: "rejected", message: `${loaded.message} Nothing was sent.` };
  }

  const lookup = authorizedLookupFromSnapshot(loaded.snapshot, parsed.userAuthority);
  const built = buildAuthorizedInstantWithdraw({
    feePayer: parsed.sender,
    userAuthority: parsed.userAuthority,
    destination: parsed.destination,
    snapshot: snapshotFromAuthorizedLookup(lookup),
    amount: parsed.amount,
  });
  if (!built.ok) return built;

  try {
    const result = await (deps.execute ?? executeWithDesk)({
      instructions: built.instructions,
      feePayer: parsed.sender,
    });
    if (typeof result.signature !== "string" || result.signature.length < 64) {
      return { ok: false, kind: "ambiguous", message: UNCONFIRMED };
    }
    return { ok: true, signature: result.signature };
  } catch (error) {
    return classifyBroadcastError(error);
  }
}

export async function sendKatanaScript(input: unknown, deps: SolSendDeps = {}): Promise<KatanaSendResult> {
  const parsed = parseRequest(input);
  if (!parsed.ok) return parsed;

  let desk: string;
  try {
    desk = deps.deskAddress ? await deps.deskAddress() : openSolFundedWallet().address;
  } catch (error) {
    if (error instanceof SolFundedKeyError) {
      return { ok: false, kind: "rejected", message: error.message };
    }
    return { ok: false, kind: "rejected", message: "The desk key could not be read. Nothing was sent." };
  }

  if (parsed.sender !== desk) {
    return { ok: false, kind: "rejected", message: SENDER_MISMATCH };
  }

  const loaded = await (deps.load ?? ((args: { owner: string; state: string }) => loadKatanaSnapshot(args, { rpc: deps.rpc })))({
    owner: parsed.sender,
    state: parsed.state,
  });
  if (!loaded.ok) {
    return { ok: false, kind: "rejected", message: `${loaded.message} Nothing was sent.` };
  }

  const owner = parseSolPubkey(parsed.sender);
  if (!owner) {
    return { ok: false, kind: "rejected", message: "The sender is not a Solana address. Nothing was sent." };
  }

  const built = buildKatanaInstructions({
    action: parsed.action,
    snapshot: loaded.snapshot,
    owner,
    amount: parsed.amount,
  });
  if (!built.ok) return built;

  try {
    const result = await (deps.execute ?? executeWithDesk)({
      instructions: built.instructions,
      feePayer: parsed.sender,
    });
    if (typeof result.signature !== "string" || result.signature.length < 64) {
      return { ok: false, kind: "ambiguous", message: UNCONFIRMED };
    }
    return { ok: true, signature: result.signature };
  } catch (error) {
    return classifyBroadcastError(error);
  }
}

async function executeWithDesk(args: SolExecuteArgs): Promise<SolExecuteResult> {
  const { keypair } = openSolFundedWallet();
  if (keypair.publicKey.toBase58() !== args.feePayer) {
    throw new SolFundedKeyError("This desk sends only from its own wallet. Nothing was sent.");
  }
  const connection = new Connection(solanaRpc(), "confirmed");
  const latest = await connection.getLatestBlockhash("confirmed");
  const tx = new Transaction();
  tx.feePayer = keypair.publicKey;
  tx.recentBlockhash = latest.blockhash;
  tx.add(...args.instructions);
  tx.sign(keypair);
  const signature = await connection.sendRawTransaction(tx.serialize(), {
    skipPreflight: false,
    preflightCommitment: "confirmed",
  });
  const confirmation = await connection.confirmTransaction(
    { signature, blockhash: latest.blockhash, lastValidBlockHeight: latest.lastValidBlockHeight },
    "confirmed",
  );
  if (confirmation.value.err) {
    throw new Error(`The transaction was included and failed. Nothing further was sent. ${JSON.stringify(confirmation.value.err)}`);
  }
  return { signature };
}

export function classifyBroadcastError(error: unknown): KatanaSendResult {
  const message = error instanceof Error ? error.message : "";
  if (/blockhash|not confirmed|timed out|timeout|ECONNRESET|socket hang up|fetch failed/i.test(message)) {
    return { ok: false, kind: "ambiguous", message: UNCONFIRMED };
  }
  if (/included and failed/i.test(message)) {
    return {
      ok: false,
      kind: "rejected",
      message: message.length < 400 ? message : `${message.slice(0, 280)}…`,
    };
  }
  if (
    /simulation failed|insufficient|Attempt to debit|no record of a prior credit|custom program error|Expired|Paused|0x1774|0x1784|Nothing was sent/i.test(
      message,
    )
  ) {
    return {
      ok: false,
      kind: "rejected",
      message: `The transaction was not accepted. Nothing was sent. ${trimChain(message)}`,
    };
  }
  if (error instanceof SolFundedKeyError) {
    return { ok: false, kind: "rejected", message: error.message };
  }
  return { ok: false, kind: "ambiguous", message: UNCONFIRMED };
}

function trimChain(message: string): string {
  return message.length > 280 ? `${message.slice(0, 280)}…` : message;
}

export type { KatanaSnapshot };
