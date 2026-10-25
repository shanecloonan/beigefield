import { Address, Dictionary, type Cell, type DictionaryValue } from "@ton/core";

export type ListedProxy = { id: number; type: number };

export type PathDefaultsResult =
  | { ok: true; jettonWallet: string; proxyId?: string }
  | { ok: false; status: 400 | 502; message: string };

/** Whitelist dict: uint32 id to (address, uint32 type). */
export const proxyWhitelistValue: DictionaryValue<{ address: Address; type: number }> = {
  serialize(value, builder) {
    builder.storeAddress(value.address).storeUint(value.type, 32);
  },
  parse(src) {
    return { address: src.loadAddress(), type: Number(src.loadUint(32)) };
  },
};

/**
 * Type 0 is proxy_ton, the native TON proxy. Prefer it. Otherwise the lowest
 * listed id other than 3, which this path uses because it is not listed.
 */
export function listedProxyId(entries: readonly ListedProxy[]): string | undefined {
  const native = entries.find((entry) => entry.type === 0);
  if (native) return String(native.id);
  const rest = entries.filter((entry) => entry.id !== 3).sort((left, right) => left.id - right.id);
  const first = rest[0];
  return first ? String(first.id) : undefined;
}

export function readListedProxies(cell: Cell): ListedProxy[] {
  const dict = Dictionary.loadDirect(Dictionary.Keys.Uint(32), proxyWhitelistValue, cell);
  return [...dict].map(([id, value]) => ({ id: Number(id), type: value.type }));
}

export async function loadPathDefaults(
  owner: string,
  deps: {
    jettonWallet: (owner: Address) => Promise<Address>;
    proxies: () => Promise<ListedProxy[]>;
  },
): Promise<PathDefaultsResult> {
  let parsed: Address;
  try {
    parsed = Address.parse(owner.trim());
  } catch {
    return { ok: false, status: 400, message: "Enter a mainnet wallet address." };
  }
  if (parsed.workChain !== 0) {
    return { ok: false, status: 400, message: "Enter a mainnet wallet address." };
  }

  let jetton: Address;
  try {
    jetton = await deps.jettonWallet(parsed);
  } catch {
    return {
      ok: false,
      status: 502,
      message:
        "The TON network did not answer, so the uTON jetton wallet was not filled. Wait a moment and try again.",
    };
  }

  let proxyId: string | undefined;
  try {
    proxyId = listedProxyId(await deps.proxies());
  } catch {
    proxyId = undefined;
  }

  return {
    ok: true,
    jettonWallet: jetton.toString({ urlSafe: true, bounceable: true, testOnly: false }),
    proxyId,
  };
}
