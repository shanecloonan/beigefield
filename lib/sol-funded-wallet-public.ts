/** Published desk address for the client bundle. No key material. */
export const SOL_FUNDED_WALLET_ADDRESS = "DnhKRJxRm3WGVqounThdefXypHKFCJfsodQKiwJxFPLb";

/** Base58 ed25519 public key: 32 bytes encode to 32–44 characters. */
const SOL_ADDRESS = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

export function isSolAddress(value: string): boolean {
  return SOL_ADDRESS.test(value);
}
