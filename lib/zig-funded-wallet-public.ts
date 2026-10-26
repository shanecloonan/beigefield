/** Published desk bech32 for the client bundle. No key material. */
export const ZIG_BECH32_PREFIX = "zig";

export const ZIG_FUNDED_WALLET_ADDRESS =
  "zig1wtkwhteg7cyr0hafjr5q20f5uesrj0e8yfx2gm";

/** Account and contract bech32 (`zig1` + 38 data chars, or longer for contracts). */
const ZIG_ADDRESS = /^zig1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{38,90}$/;

export function isZigAddress(value: string): boolean {
  return ZIG_ADDRESS.test(value);
}
