/**
 * Server-side signer for the Solana desk wallet. The secret key stays in this
 * module so a client component does not ship it. Do not import this file from
 * a client component. `SOL_FUNDED_SECRET_KEY` (base58, 64 bytes) overrides the
 * built-in key when it is set.
 */
import { Keypair } from "@solana/web3.js";
import bs58 from "bs58";
import { SOL_FUNDED_WALLET_ADDRESS } from "@/lib/sol-funded-wallet-public";

const SECRET_KEY =
  "4LPeWWG1XvWDR4ezhdgu3FHboqcFDfkVmmanJWYxcKGgaHmSmCKbVDFqQ33rNj9r8BNEZ19dcDmTk2gKR2L8qVSX";

export class SolFundedKeyError extends Error {
  constructor(message = "The desk key could not be read. Nothing was sent.") {
    super(message);
    this.name = "SolFundedKeyError";
  }
}

let cachedSecret: string | null = null;
let cached: Keypair | null = null;

function configured(name: string): string | undefined {
  const value = process.env[name];
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function deskSecret(): string {
  return configured("SOL_FUNDED_SECRET_KEY") ?? SECRET_KEY;
}

export function textContainsSolSecret(text: string): boolean {
  return text.includes(SECRET_KEY);
}

export function openSolFundedWallet(): { address: string; keypair: Keypair } {
  const secret = deskSecret();
  if (!cached || cachedSecret !== secret) {
    let keypair: Keypair;
    try {
      const bytes = bs58.decode(secret);
      if (bytes.length !== 64) throw new SolFundedKeyError();
      keypair = Keypair.fromSecretKey(bytes);
    } catch {
      cached = null;
      cachedSecret = null;
      throw new SolFundedKeyError();
    }
    cached = keypair;
    cachedSecret = secret;
  }
  return { address: cached.publicKey.toBase58(), keypair: cached };
}

/** Base58 for display. The published desk address when the signer cannot be opened. */
export function deskPublicAddress(): string {
  try {
    return openSolFundedWallet().address;
  } catch {
    return SOL_FUNDED_WALLET_ADDRESS;
  }
}
