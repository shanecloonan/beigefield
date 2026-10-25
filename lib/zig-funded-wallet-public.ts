/**
 * Published desk bech32 for the client bundle. No key material.
 * `NEXT_PUBLIC_ZIG_FUNDED_ADDRESS` is optional. The page and
 * `/api/zig/path-defaults` supply the address derived on the server.
 */

function publishedAddress(): string {
  const value = process.env.NEXT_PUBLIC_ZIG_FUNDED_ADDRESS;
  return typeof value === "string" ? value.trim() : "";
}

export const ZIG_BECH32_PREFIX = "zig";

export const ZIG_FUNDED_WALLET_ADDRESS = publishedAddress();

/** Account and contract bech32 (`zig1` + 38 data chars, or longer for contracts). */
const ZIG_ADDRESS = /^zig1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{38,90}$/;

export function isZigAddress(value: string): boolean {
  return ZIG_ADDRESS.test(value);
}
