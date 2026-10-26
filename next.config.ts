import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // postgres.js uses Node networking; keep it out of the server bundle.
  // CosmJS stays in the server bundle. Turbopack's hashed
  // serverExternalPackages aliases are not resolvable on Vercel, and every
  // route that imported them returned 500.
  serverExternalPackages: ["postgres"],
};

export default nextConfig;
