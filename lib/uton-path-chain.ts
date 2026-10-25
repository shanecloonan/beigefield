import "server-only";
import { Address } from "@ton/core";
import { JettonMaster, TonClient } from "@ton/ton";
import { readListedProxies, type ListedProxy } from "@/lib/uton-path-defaults";
import { utonMinter } from "@/lib/uton";

const DEFAULT_ENDPOINT = "https://toncenter.com/api/v2/jsonRPC";

export function createPathDefaultDeps(): {
  jettonWallet: (owner: Address) => Promise<Address>;
  proxies: () => Promise<ListedProxy[]>;
} {
  const client = new TonClient({
    endpoint: process.env.TONCENTER_ENDPOINT?.trim() || DEFAULT_ENDPOINT,
    apiKey: process.env.TONCENTER_API_KEY?.trim() || undefined,
    timeout: 20_000,
  });
  const minter = Address.parse(utonMinter);
  const master = client.open(JettonMaster.create(minter));
  return {
    jettonWallet: (owner) => master.getWalletAddress(owner),
    proxies: async () => {
      const result = await client.runMethod(minter, "get_minter_data");
      result.stack.readBigNumber();
      result.stack.readBigNumber();
      result.stack.readBigNumber();
      result.stack.readBigNumber();
      result.stack.readAddress();
      result.stack.readAddressOpt();
      return readListedProxies(result.stack.readCell());
    },
  };
}
