/** Chain names the Blend desk can show. Safe to import from a client component. */

export const DEFAULT_CHAIN = "ethereum";

export const CHAIN_FILTERS = [
  { id: "ethereum", label: "Ethereum" },
  { id: "bsc", label: "BNB" },
  { id: "arbitrum", label: "Arbitrum" },
  { id: "base", label: "Base" },
  { id: "solana", label: "Solana" },
  { id: "all", label: "All" },
] as const;

export function normalizeChain(value: unknown): string {
  const text = String(value ?? "").trim().toLowerCase();
  if (!text || text === "eth" || text === "mainnet") return DEFAULT_CHAIN;
  if (text === "bnb" || text === "bnb-chain" || text === "binance") return "bsc";
  if (text === "arb" || text === "arbitrum-one") return "arbitrum";
  return text;
}
