import "server-only";
import { Address } from "@ton/core";
import { TonClient } from "@ton/ton";
import { readListedProxies, type ListedProxy } from "@/lib/uton-path-defaults";
import { readJettonWallet, TONCENTER_ENDPOINT } from "@/lib/ton-rpc";
import { utonMinter } from "@/lib/uton";

export function createPathDefaultDeps(): {
  jettonWallet: (owner: Address) => Promise<Address>;
  proxies: () => Promise<ListedProxy[]>;
} {
  const minter = Address.parse(utonMinter);
  const endpoint = process.env.TONCENTER_ENDPOINT?.trim() || TONCENTER_ENDPOINT;
  const apiKey = process.env.TONCENTER_API_KEY?.trim() || undefined;
  return {
    jettonWallet: async (owner) => {
      const wallet = await readJettonWallet(owner, minter);
      if (!wallet) throw new Error("The TON network did not answer.");
      return wallet;
    },
    proxies: () => readProxies(minter, endpoint, apiKey),
  };
}

async function readProxies(minter: Address, endpoint: string, apiKey: string | undefined): Promise<ListedProxy[]> {
  try {
    const client = new TonClient({ endpoint, apiKey, timeout: 3_500 });
    const result = await client.runMethod(minter, "get_minter_data");
    result.stack.readBigNumber();
    result.stack.readBigNumber();
    result.stack.readBigNumber();
    result.stack.readBigNumber();
    result.stack.readAddress();
    result.stack.readAddressOpt();
    return readListedProxies(result.stack.readCell());
  } catch {
    return [];
  }
}
