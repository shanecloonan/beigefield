import assert from "node:assert/strict";
import test from "node:test";
import {
  classifyOutcome,
  isBigOrCanonicalName,
  isValidAddress,
  loadMasterLists,
  normalizeAddress,
  runMatchesList,
  sketchyScore,
  type ListContract,
} from "./lists.ts";

test("address validation rejects short strings and accepts 40 hex chars", () => {
  assert.equal(isValidAddress("0x1234"), false);
  assert.equal(
    normalizeAddress("0xABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCD"),
    "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
  );
});

test("outcome buckets follow funds_in_heat and caller profit", () => {
  assert.equal(classifyOutcome(null), null);
  assert.equal(classifyOutcome({ heat: 0 }), "no");
  assert.equal(classifyOutcome({ heat: 3, heat_breakdown: { funds_in_heat: 0 } }), "maybe");
  assert.equal(classifyOutcome({ heat: 4, heat_breakdown: { funds_in_heat: 2 } }), "drain");
  assert.equal(classifyOutcome({ heat: 1, notes: ["caller_profit_delta=5"] }), "drain");
  assert.equal(classifyOutcome({ heat: 1, notes: ["caller_profit_delta=0"] }), "maybe");
});

test("legacy master_list rows belong to list 1", () => {
  assert.equal(runMatchesList({ discovery_source: "master_list" }, "list-1"), true);
  assert.equal(runMatchesList({ discovery_source: "master_list" }, "list-2"), false);
  assert.equal(runMatchesList({ list_id: "list-2", discovery_source: "master_list" }, "list-2"), true);
  const list2Key = `master-list:list-2:0x${"ab".repeat(20)}`;
  assert.equal(runMatchesList({ dedupe_key: list2Key, discovery_source: "master_list" }, "list-2"), true);
  assert.equal(runMatchesList({ dedupe_key: list2Key, discovery_source: "master_list" }, "list-1"), false);
});

test("named lists keep list 1 and load the sketchy list 2 file", () => {
  const { lists, random_scan } = loadMasterLists();
  const one = lists.find((list) => list.id === "list-1");
  const two = lists.find((list) => list.id === "list-2");
  assert.ok(one);
  assert.ok(two);
  assert.equal(one.min_funds_usd, 2000);
  assert.equal(one.max_funds_usd, 9_000_000);
  assert.equal(two.min_funds_usd, 50);
  assert.equal(two.max_funds_usd, 1900);
  assert.equal(one.contracts[0]?.address, "0x657d9aba1dbb59e53f9f3ecaa878447dcfc96dcb");
  assert.equal(two.source, "list2_candidates");
  assert.equal(two.total, 313);
  assert.equal(two.total_usd, 211226.03);
  assert.equal(random_scan.enabled, true);
  assert.equal(random_scan.gap_ms, 8000);
  const sushi = two.contracts.find((row) => /sushi|uniswap|aave/i.test(row.protocol));
  assert.equal(sushi, undefined);
});

test("sketchy score prefers a hacked abandoned contract over a generic label", () => {
  const { lists } = loadMasterLists();
  const rulesDoc = {
    below_floor_marker: "below-2000",
    exclude_reason_markers: ["canonical:"],
    exclude_name_substrings: ["sushiswap"],
    exclude_exact_names: [],
    generic_labels: ["erc4626vault"],
    sketchy_weights: [
      { pattern: "past-hack|abandoned", weight: 40 },
      { pattern: "unknown", weight: 10 },
    ],
  };
  const hacked = sketchyScore("past-hack abandoned", "Percent Finance", rulesDoc);
  const generic = sketchyScore("vault", "ERC-4626 vault", rulesDoc);
  assert.ok(hacked > generic);
  assert.equal(isBigOrCanonicalName("SushiSwap", "sushiswap", rulesDoc), true);
  assert.equal(isBigOrCanonicalName("univ2-fork-unknown", "univ2-fork-unknown", rulesDoc), false);
  const two = lists.find((list) => list.id === "list-2");
  const ranked: ListContract[] = two?.contracts.filter((row) => !row.manual) ?? [];
  assert.ok(ranked.length > 1);
  assert.match(ranked[0]?.candidate_reason || "", /fresh-pick/);
  assert.match(ranked[0]?.candidate_reason || "", /not-exploited/);
});
