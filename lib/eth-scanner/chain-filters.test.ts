import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { CHAIN_FILTERS, DEFAULT_CHAIN, normalizeChain } from "./chain-filters";

describe("blend chain filter", () => {
  it("keeps Ethereum as the default and lists the other EVM chains", () => {
    assert.equal(DEFAULT_CHAIN, "ethereum");
    assert.deepEqual(
      CHAIN_FILTERS.map((item) => item.id),
      ["ethereum", "bsc", "arbitrum", "base", "optimism", "polygon", "solana", "all"],
    );
    assert.equal(normalizeChain(""), "ethereum");
    assert.equal(normalizeChain("op"), "optimism");
    assert.equal(normalizeChain("matic"), "polygon");
    assert.equal(normalizeChain("bnb"), "bsc");
  });

  it("badges a chain on the blend board and schedules a modest monitor", () => {
    const board = readFileSync(new URL("../../app/blend/blend-app.tsx", import.meta.url), "utf8");
    assert.match(board, /border-brand-700/);
    assert.match(board, /\{row\.chain \|\| "ethereum"\}/);
    const workflow = readFileSync(
      new URL("../../.github/workflows/evm-scanner-monitor.yml", import.meta.url),
      "utf8",
    );
    assert.match(workflow, /20 \*\/6 \* \* \*/);
    for (const chain of ["bsc", "arbitrum", "base", "optimism", "polygon"]) {
      assert.match(workflow, new RegExp(chain));
    }
    assert.match(workflow, /discover soft-failed/);
    assert.match(workflow, /max-parallel: 1/);
    const eth = readFileSync(
      new URL("../../.github/workflows/eth-scanner-monitor.yml", import.meta.url),
      "utf8",
    );
    assert.match(eth, /\*\/10 \* \* \* \*/);
  });
});
