import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // postgres.js uses Node networking; keep it out of the server bundle.
  serverExternalPackages: [
    "postgres",
    "@cosmjs/cosmwasm-stargate",
    "@cosmjs/cosmwasm",
    "@cosmjs/stargate",
    "@cosmjs/proto-signing",
    "@cosmjs/tendermint-rpc",
    "@cosmjs/crypto",
    "cosmjs-types",
  ],
};

export default nextConfig;
