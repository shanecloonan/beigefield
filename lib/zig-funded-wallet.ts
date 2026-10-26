/**
 * Server-side signer for the ZIGChain desk wallet. The recovery phrase stays
 * in this module so a client component does not ship it. Do not import this
 * file from a client component. `ZIG_FUNDED_MNEMONIC` overrides the built-in
 * phrase when it is set.
 */
import { DirectSecp256k1HdWallet } from "@cosmjs/proto-signing";
import {
  ZIG_BECH32_PREFIX,
  ZIG_FUNDED_WALLET_ADDRESS,
  isZigAddress,
} from "@/lib/zig-funded-wallet-public";

const MNEMONIC = [
  "pull",
  "injury",
  "toward",
  "gentle",
  "jacket",
  "office",
  "hover",
  "honey",
  "accuse",
  "budget",
  "bird",
  "sponsor",
  "current",
  "govern",
  "media",
  "series",
  "color",
  "gloom",
  "peanut",
  "maple",
  "concert",
  "face",
  "wasp",
  "gloom",
] as const;

export class ZigFundedKeyError extends Error {
  constructor(message = "The desk key could not be read. Nothing was sent.") {
    super(message);
    this.name = "ZigFundedKeyError";
  }
}

type Opened = { address: string; wallet: DirectSecp256k1HdWallet };

let cachedMnemonic: string | null = null;
let cached: Promise<Opened> | null = null;

function configured(name: string): string | undefined {
  const value = process.env[name];
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function deskMnemonic(): string {
  return configured("ZIG_FUNDED_MNEMONIC") ?? MNEMONIC.join(" ");
}

export function textContainsZigMnemonic(text: string): boolean {
  const compact = text.toLowerCase();
  let from = 0;
  for (const word of MNEMONIC) {
    const at = compact.indexOf(word, from);
    if (at < 0) return false;
    from = at + word.length;
  }
  return true;
}

export async function openZigFundedWallet(): Promise<Opened> {
  const mnemonic = deskMnemonic();
  if (!cached || cachedMnemonic !== mnemonic) {
    cachedMnemonic = mnemonic;
    const pending = DirectSecp256k1HdWallet.fromMnemonic(mnemonic, {
      prefix: ZIG_BECH32_PREFIX,
    }).then(async (wallet) => {
      const [account] = await wallet.getAccounts();
      if (!account || !isZigAddress(account.address)) {
        throw new ZigFundedKeyError("The desk key could not be read. Nothing was sent.");
      }
      return { wallet, address: account.address };
    });
    cached = pending.catch((error: unknown) => {
      if (cached === pending) {
        cached = null;
        cachedMnemonic = null;
      }
      if (error instanceof ZigFundedKeyError) throw error;
      throw new ZigFundedKeyError("The desk key could not be read. Nothing was sent.");
    });
  }
  return cached;
}

/** Bech32 for display. The published desk address when the signer cannot be opened. */
export async function deskPublicAddress(): Promise<string> {
  try {
    const opened = await openZigFundedWallet();
    return opened.address;
  } catch {
    return isZigAddress(ZIG_FUNDED_WALLET_ADDRESS) ? ZIG_FUNDED_WALLET_ADDRESS : "";
  }
}
