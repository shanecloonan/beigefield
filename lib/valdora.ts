/**
 * ZIGChain mainnet constants for the Valdora staker path.
 * Chain id is the LCD `network` field from
 * `/cosmos/base/tendermint/v1beta1/node_info`, confirmed again on
 * `https://public-zigchain-rpc.numia.xyz/status` (`node_info.network`).
 * The LCD node's own `rpc_address` is a local bind (`tcp://0.0.0.0:26657`);
 * the public Tendermint RPC below is the Numia endpoint that reports the same chain id.
 */

function configured(name: string): string | undefined {
  const value = process.env[name];
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

export const ZIG_CHAIN_ID = "zigchain-1";

export const ZIG_LCD = configured("ZIG_LCD") ?? "https://public-zigchain-lcd.numia.xyz";

export const ZIG_RPC = configured("ZIG_RPC") ?? "https://public-zigchain-rpc.numia.xyz";

/** Integer form of the LCD minimum_gas_price (`2500000000.000000000000000000azig`). */
export const ZIG_MIN_GAS_PRICE = "2500000000azig";

export const VALDORA_STAKER =
  "zig18nnde5tpn76xj3wm53n0tmuf3q06nruj3p6kdemcllzxqwzkpqzqk7ue55";

export const VALDORA_CODE_ID = 179;

export const VALDORA_STZIG_TOKEN =
  "zig109f7g2rzl2aqee7z6gffn8kfe9cpqx0mjkk7ethmx8m2hq4xpe9snmaam2";

export const NATIVE_DENOM = "azig";

export const MSG_EXECUTE_TYPE_URL = "/cosmwasm.wasm.v1.MsgExecuteContract";

/** Chain-registry explorer templates for zigscan. */
export function zigExplorerTxUrl(txHash: string): string {
  return `https://www.zigscan.org/tx/${encodeURIComponent(txHash)}`;
}

export function zigExplorerAccountUrl(address: string): string {
  return `https://www.zigscan.org/address/${encodeURIComponent(address)}`;
}

export function zigGasPrice(): string {
  const configuredPrice = configured("ZIG_GAS_PRICE");
  if (configuredPrice && /^\d+azig$/.test(configuredPrice)) return configuredPrice;
  return ZIG_MIN_GAS_PRICE;
}

/** Msg body for the path execute. Caller validates `id` first. */
export function withdrawByIdMsg(id: number | string) {
  return { withdraw_unbonded_by_id: { id: Number(id) } };
}

export function readUnbondingId(id: unknown): number | null {
  if (typeof id === "string") {
    if (!/^\d+$/.test(id.trim())) return null;
    return readUnbondingId(Number(id));
  }
  if (typeof id !== "number" || !Number.isSafeInteger(id) || id < 0) return null;
  return id;
}
