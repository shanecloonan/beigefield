/**
 * Server-side signer for the desk wallet. The recovery phrase stays in this
 * module so a client component does not ship it. Do not import this file from
 * a client component.
 */
import { mnemonicToPrivateKey, type KeyPair } from "@ton/crypto";
import { WalletContractV5R1 } from "@ton/ton";
import {
  Address,
  Cell,
  SendMode,
  beginCell,
  external,
  internal,
  storeMessage,
  type MessageRelaxed,
} from "@ton/core";

const MNEMONIC = [
  "fatigue",
  "slush",
  "cave",
  "purse",
  "opera",
  "enlist",
  "type",
  "slogan",
  "furnace",
  "carpet",
  "escape",
  "same",
  "color",
  "minute",
  "success",
  "twenty",
  "marriage",
  "off",
  "utility",
  "flag",
  "champion",
  "enemy",
  "execute",
  "stay",
] as const;

let keysPromise: Promise<KeyPair> | null = null;

export function textContainsFundedMnemonic(text: string): boolean {
  const compact = text.toLowerCase();
  let from = 0;
  for (const word of MNEMONIC) {
    const at = compact.indexOf(word, from);
    if (at < 0) return false;
    from = at + word.length;
  }
  return true;
}

export async function openFundedWallet(): Promise<{
  keys: KeyPair;
  wallet: WalletContractV5R1;
}> {
  keysPromise ??= mnemonicToPrivateKey([...MNEMONIC]);
  const keys = await keysPromise;
  const wallet = WalletContractV5R1.create({
    workchain: 0,
    publicKey: keys.publicKey,
  });
  return { keys, wallet };
}

export async function signFundedExternal(args: {
  seqno: number;
  timeout: number;
  includeInit: boolean;
  messages: MessageRelaxed[];
}): Promise<Buffer> {
  const { keys, wallet } = await openFundedWallet();
  const transfer = wallet.createTransfer({
    seqno: args.seqno,
    timeout: args.timeout,
    secretKey: keys.secretKey,
    authType: "external",
    sendMode: (SendMode.PAY_GAS_SEPARATELY +
      SendMode.IGNORE_ERRORS) as SendMode,
    messages: args.messages,
  });
  const body = transfer instanceof Promise ? await transfer : transfer;
  const message = external({
    to: wallet.address,
    body,
    init: args.includeInit ? wallet.init : undefined,
  });
  return beginCell().store(storeMessage(message)).endCell().toBoc();
}

export function relaxedMessage(args: {
  address: string;
  nanotons: bigint;
  body?: Cell;
}): MessageRelaxed {
  const parsed = Address.parseFriendly(args.address);
  return internal({
    to: parsed.address,
    value: args.nanotons,
    bounce: parsed.isBounceable,
    body: args.body,
  });
}
