/**
 * Server-side signer for the ZIGChain desk wallet.
 * The recovery phrase stays in `ZIG_FUNDED_MNEMONIC` and is never sent to the client.
 * Do not import this file from a client component.
 */
import { DirectSecp256k1HdWallet } from "@cosmjs/proto-signing";
import { ZIG_BECH32_PREFIX, isZigAddress } from "@/lib/zig-funded-wallet-public";

export class ZigFundedKeyError extends Error {
  constructor(message = "The desk key is not configured. Nothing was sent.") {
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

export async function openZigFundedWallet(): Promise<Opened> {
  const mnemonic = configured("ZIG_FUNDED_MNEMONIC");
  if (!mnemonic) throw new ZigFundedKeyError();
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

/** Bech32 for display. Empty when the desk key is unset and no published address is configured. */
export async function deskPublicAddress(): Promise<string> {
  try {
    const opened = await openZigFundedWallet();
    return opened.address;
  } catch {
    const published = configured("ZIG_FUNDED_ADDRESS") ?? configured("NEXT_PUBLIC_ZIG_FUNDED_ADDRESS");
    return published && isZigAddress(published) ? published : "";
  }
}
