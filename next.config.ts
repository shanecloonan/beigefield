import type { NextConfig } from "next";

/**
 * /test ETH scanner: the Python package, fixtures, defensive fuzz harness and
 * (on Vercel) the portable CPython from scripts/bundle-python-runtime.mjs
 * must be traced into the routes that spawn them. Exact route keys only —
 * a bare `/api/test` prefix would also match `/api/testnet`.
 */
const pythonTrace = [
  "./eth-scanner/src/**/*",
  "./eth-scanner/tests/fixtures/**/*",
  "./eth-scanner/.runtime/**/*",
];
const deskTrace = ["./eth-scanner/tests/fixtures/**/*", "./eth-scanner/research/fuzz/**/*"];
const noRuntime = ["./eth-scanner/.runtime/**/*"];

const nextConfig: NextConfig = {
  // postgres.js uses Node networking; keep it out of the server bundle.
  // CosmJS stays in the server bundle. Turbopack's hashed
  // serverExternalPackages aliases are not resolvable on Vercel, and every
  // route that imported them returned 500.
  serverExternalPackages: ["postgres"],
  outputFileTracingIncludes: {
    "/api/test/run": pythonTrace,
    "/api/test/research": pythonTrace,
    "/api/test/engines": deskTrace,
  },
  outputFileTracingExcludes: {
    "/api/test": noRuntime,
    "/api/test/receipt": noRuntime,
    "/api/test/engines": noRuntime,
  },
};

export default nextConfig;
