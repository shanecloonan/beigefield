/**
 * Lightest Solana browser-wallet surface that fits this repo: the injected
 * Phantom / Solflare provider. No wallet-adapter package.
 */

export type SolanaInjectedProvider = {
  publicKey?: { toBase58(): string } | null;
  isPhantom?: boolean;
  isConnected?: boolean;
  connect(opts?: { onlyIfTrusted?: boolean }): Promise<{ publicKey: { toBase58(): string } }>;
  disconnect(): Promise<void>;
  signAndSendTransaction(
    transaction: unknown,
    options?: { skipPreflight?: boolean },
  ): Promise<{ signature: string } | string>;
  on?(event: "connect" | "disconnect" | "accountChanged", handler: (publicKey?: { toBase58(): string } | null) => void): void;
  off?(event: "connect" | "disconnect" | "accountChanged", handler: (publicKey?: { toBase58(): string } | null) => void): void;
  removeListener?(
    event: "connect" | "disconnect" | "accountChanged",
    handler: (publicKey?: { toBase58(): string } | null) => void,
  ): void;
};

type InjectedWindow = Window & {
  phantom?: { solana?: SolanaInjectedProvider };
  solana?: SolanaInjectedProvider;
  solflare?: SolanaInjectedProvider;
};

export function getSolanaProvider(): SolanaInjectedProvider | null {
  if (typeof window === "undefined") return null;
  const injected = window as InjectedWindow;
  if (injected.phantom?.solana) return injected.phantom.solana;
  if (injected.solana) return injected.solana;
  if (injected.solflare) return injected.solflare;
  return null;
}

export function readWalletSignature(result: { signature: string } | string | null | undefined): string | null {
  if (typeof result === "string" && result.length >= 64) return result;
  if (result && typeof result === "object" && typeof result.signature === "string" && result.signature.length >= 64) {
    return result.signature;
  }
  return null;
}
