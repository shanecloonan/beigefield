/** Mainnet uTON jetton minter. Static reference. The notes do not read chain state. */
export const utonMinter = "EQAfF5j3JMIpZlLmACv7Ub7RH7WmiVMuV4ivcgNYHvNnqHTz";

export const utonSource = {
  repo: "UTONICFinance/utonic-contracts-uTON",
  commit: "b92e6742f8597d6cd8cdd04afec88f93da159932",
  short: "b92e674",
} as const;

const githubRoot = `https://github.com/${utonSource.repo}`;
const atCommit = `${githubRoot}/blob/${utonSource.commit}`;

export const utonLinks = {
  tree: `${githubRoot}/tree/${utonSource.commit}`,
  docs: `${atCommit}/docs/README.md`,
  interface: `${atCommit}/docs/user-interface.tlb`,
  wallet: `${atCommit}/contracts/wallet.func`,
  minter: `${atCommit}/contracts/minter.func`,
  proxyTon: `${atCommit}/contracts/proxy/proxy_ton/proxy_ton.func`,
  withdraw: `${atCommit}/contracts/proxy/proxy_ton/withdraw/withdraw.func`,
  tonviewer: `https://tonviewer.com/${utonMinter}`,
} as const;
