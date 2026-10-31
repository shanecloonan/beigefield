import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { capabilityNote, etherscanApiKeys, scannerCapabilities, supabaseUrl } from "./capabilities";

const saved = {
  ETHERSCAN_API_KEYS: process.env.ETHERSCAN_API_KEYS,
  SUPABASE_SERVICE_ROLE_KEY: process.env.SUPABASE_SERVICE_ROLE_KEY,
  SUPABASE_URL: process.env.SUPABASE_URL,
  NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
  ETH_SCANNER_SUPABASE_URL: process.env.ETH_SCANNER_SUPABASE_URL,
  ETH_SCANNER_DRY_RUN: process.env.ETH_SCANNER_DRY_RUN,
};

afterEach(() => {
  for (const [k, v] of Object.entries(saved)) {
    if (v == null) delete process.env[k];
    else process.env[k] = v;
  }
});

describe("etherscan keys come from env only", () => {
  it("has no live ingest when ETHERSCAN_API_KEYS is unset", () => {
    delete process.env.ETHERSCAN_API_KEYS;
    assert.equal(etherscanApiKeys(), "");
    assert.equal(scannerCapabilities().live_ingest, false);
  });

  it("treats a blank value as unset", () => {
    process.env.ETHERSCAN_API_KEYS = "   ";
    assert.equal(scannerCapabilities().live_ingest, false);
  });

  it("uses a set ETHERSCAN_API_KEYS value", () => {
    process.env.ETHERSCAN_API_KEYS = "override-key, second-key";
    assert.equal(etherscanApiKeys(), "override-key, second-key");
    assert.equal(scannerCapabilities().live_ingest, true);
  });

  it("never puts key values in capability notes", () => {
    process.env.ETHERSCAN_API_KEYS = "super-secret-key";
    const note = capabilityNote(scannerCapabilities());
    assert.equal(note.includes("super-secret-key"), false);
  });
});

describe("supabase persist needs both URL and service role", () => {
  it("stays dry-run without a URL", () => {
    delete process.env.SUPABASE_URL;
    delete process.env.ETH_SCANNER_SUPABASE_URL;
    process.env.NEXT_PUBLIC_SUPABASE_URL = "https://public-site.supabase.co";
    delete process.env.ETH_SCANNER_DRY_RUN;
    process.env.SUPABASE_SERVICE_ROLE_KEY = "role";
    assert.equal(supabaseUrl(), "");
    assert.equal(scannerCapabilities().persist_remote, false);
  });

  it("persists when URL + role are set", () => {
    delete process.env.ETH_SCANNER_DRY_RUN;
    process.env.SUPABASE_URL = "https://example.supabase.co/";
    process.env.SUPABASE_SERVICE_ROLE_KEY = "role";
    assert.equal(supabaseUrl(), "https://example.supabase.co");
    assert.equal(scannerCapabilities().persist_remote, true);
  });
});
