import assert from "node:assert/strict";
import test from "node:test";
import { livenessOf, summarizeBlendRuns, verdictOf } from "./blend-board";

const ADDR_A = "0x1111111111111111111111111111111111111111";
const ADDR_B = "0x2222222222222222222222222222222222222222";
const ADDR_C = "0x3333333333333333333333333333333333333333";

test("drain-found is Yes, and heat without a drain is Maybe", () => {
  assert.equal(verdictOf({ blend_bucket: "drain-found" }).label, "Yes");
  assert.equal(verdictOf({ blend_bucket: "maybe", heat: 0 }).verdict, "maybe");
  assert.equal(verdictOf({ heat: 4, bucket: "lane-b-queue" }).verdict, "maybe");
  assert.equal(verdictOf({ heat: 0, bucket: "lane-a-cool" }).verdict, "no");
  assert.equal(
    verdictOf({ heat: 1, heat_breakdown: { funds_in_heat: 50 } }).verdict,
    "yes",
  );
});

test("one contract, highest heat, and the three desk totals", () => {
  const board = summarizeBlendRuns([
    { address: ADDR_A, blend_bucket: "no", blend_heat: 0, heat: 0, status: "done", funds_usd: 100 },
    {
      address: ADDR_A.toUpperCase(),
      blend_bucket: "drain-found",
      blend_heat: 9,
      heat: 2,
      status: "done",
      funds_usd: 4000,
      contract_name: "Vault",
      created_at: "2026-01-02T00:00:00Z",
    },
    { address: ADDR_B, heat: 3, bucket: "manual-review", status: "done", tvl_usd: 80, created_at: "2026-01-03T00:00:00Z" },
    { address: ADDR_C, blend_bucket: "no", heat: 0, status: "dropped", money_at_risk_usd: 10 },
    { address: ADDR_A, blend_bucket: "maybe", blend_heat: 9, status: "done", created_at: "2026-01-01T00:00:00Z" },
    { address: "0x4444444444444444444444444444444444444444", status: "running", heat: 99, blend_bucket: "drain-found" },
    { address: "not-an-address", status: "done", heat: 50 },
  ]);
  assert.equal(board.scanned, 3);
  assert.equal(board.totals.yes, 1);
  assert.equal(board.totals.maybe, 1);
  assert.equal(board.totals.no, 1);
  assert.equal(board.totals.other, 0);
  assert.equal(board.leaderboard[0].address, ADDR_A);
  assert.equal(board.leaderboard[0].heat, 9);
  assert.equal(board.leaderboard[0].label, "Yes");
  assert.equal(board.leaderboard[0].funds_usd, 4000);
  assert.equal(board.leaderboard[0].contract_name, "Vault");
  assert.equal(board.leaderboard[1].address, ADDR_B);
  assert.equal(board.leaderboard[1].funds_usd, 80);
  assert.equal(board.leaderboard[2].label, "No");
});

test("the leaderboard keeps the top 100 and ranks funds after heat", () => {
  const rows = Array.from({ length: 120 }, (_, i) => ({
    address: `0x${(i + 1).toString(16).padStart(40, "0")}`,
    heat: i < 110 ? 1 : 0,
    funds_usd: i,
    blend_bucket: i % 2 === 0 ? "maybe" : "no",
    status: "done",
  }));
  const board = summarizeBlendRuns(rows);
  assert.equal(board.scanned, 120);
  assert.equal(board.leaderboard.length, 100);
  assert.ok(board.leaderboard.every((row) => row.heat === 1));
  assert.ok(board.leaderboard[0].funds_usd! > board.leaderboard[1].funds_usd!);
  assert.equal(board.totals.yes + board.totals.maybe + board.totals.no + board.totals.other, 120);
  assert.equal(board.flagged.length, 0);
});

test("a collapsed outflow stays on the heat ranking with a liveness label", () => {
  const board = summarizeBlendRuns([
    {
      address: ADDR_A,
      heat: 12,
      blend_bucket: "drain-found",
      status: "done",
      heat_breakdown: { liveness: { status: "already-exploited", heat_contribution: 0 } },
    },
    { address: ADDR_B, heat: 2, blend_bucket: "maybe", status: "done" },
  ]);
  assert.equal(livenessOf({ heat_breakdown: { liveness: { status: "dead" } } }), "dead");
  assert.equal(board.scanned, 2);
  assert.equal(board.totals.yes, 1);
  assert.equal(board.leaderboard.length, 2);
  assert.equal(board.leaderboard[0].address, ADDR_A);
  assert.equal(board.leaderboard[0].liveness, "already-exploited");
  assert.equal(board.leaderboard[1].address, ADDR_B);
  assert.equal(board.flagged.length, 1);
  assert.equal(board.flagged[0].address, ADDR_A);
  assert.equal(board.flagged[0].liveness, "already-exploited");
});

test("the rank uses all-time heat and keeps the latest scan beside it", () => {
  const now = Date.parse("2026-11-21T00:00:00Z");
  const board = summarizeBlendRuns(
    [
      {
        address: ADDR_A,
        heat: 9,
        blend_bucket: "maybe",
        status: "done",
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        address: ADDR_A,
        heat: 1,
        blend_bucket: "maybe",
        status: "done",
        created_at: "2026-11-20T00:00:00Z",
        funds_usd: 50,
      },
      {
        address: ADDR_B,
        heat: 4,
        blend_bucket: "maybe",
        status: "done",
        created_at: "2026-10-01T00:00:00Z",
      },
    ],
    100,
    now,
  );
  assert.equal(board.leaderboard[0].address, ADDR_A);
  assert.equal(board.leaderboard[0].heat, 1);
  assert.equal(board.leaderboard[0].peak_heat, 9);
  assert.equal(board.leaderboard[0].history_count, 2);
  assert.equal(board.leaderboard[1].address, ADDR_B);
  assert.equal(board.leaderboard[1].heat, 4);
  assert.equal(board.leaderboard[1].peak_heat, 4);
  assert.equal(board.leaderboard[0].stale, false);
  assert.equal(board.requeue.length, 1);
  assert.equal(board.requeue[0].address, ADDR_B);
  assert.equal(board.requeue[0].peak_heat, 4);
  assert.equal(board.chain, "ethereum");
  assert.equal(board.leaderboard[0].chain, "ethereum");
});

test("the same scan repeated by a second query counts once", () => {
  const row = {
    address: ADDR_A,
    heat: 12,
    blend_bucket: "maybe",
    status: "done",
    created_at: "2026-11-01T00:00:00Z",
    funds_usd: 1000,
  };
  const board = summarizeBlendRuns([row, { ...row }, { ...row, heat: 4, created_at: "2026-11-20T00:00:00Z" }]);
  assert.equal(board.leaderboard[0].history_count, 2);
  assert.equal(board.leaderboard[0].peak_heat, 12);
  assert.equal(board.leaderboard[0].heat, 4);
});

test("a solana row does not change the ethereum totals", () => {
  const eth = [
    { address: ADDR_A, heat: 3, blend_bucket: "maybe", status: "done", funds_usd: 200 },
  ];
  const solana = {
    address: "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    chain: "solana",
    heat: 9,
    blend_bucket: "drain-found",
    status: "done",
    funds_usd: 1_000_000,
  };
  const ethOnly = summarizeBlendRuns(eth);
  const mixed = summarizeBlendRuns([...eth, solana]);
  assert.equal(mixed.chain, "ethereum");
  assert.equal(mixed.scanned, ethOnly.scanned);
  assert.equal(mixed.totals.maybe, ethOnly.totals.maybe);
  assert.equal(mixed.totals.yes, 0);
  assert.equal(mixed.leaderboard.length, 1);
  assert.equal(mixed.leaderboard[0].address, ADDR_A);
  const sol = summarizeBlendRuns([...eth, solana], 100, Date.now(), "solana");
  assert.equal(sol.scanned, 1);
  assert.equal(sol.totals.yes, 1);
  assert.equal(sol.leaderboard[0].chain, "solana");
  assert.equal(sol.leaderboard[0].heat, 9);
});

test("bnb, arbitrum, and base rows stay out of the ethereum totals", () => {
  const rows = [
    { address: ADDR_A, heat: 3, blend_bucket: "maybe", status: "done", funds_usd: 200 },
    { address: ADDR_B, chain: "bsc", heat: 8, blend_bucket: "drain-found", status: "done", funds_usd: 900 },
    { address: ADDR_C, chain: "arbitrum", heat: 2, blend_bucket: "no", status: "done" },
    { address: ADDR_A, chain: "base", heat: 5, blend_bucket: "maybe", status: "done", funds_usd: 40 },
  ];
  const eth = summarizeBlendRuns(rows);
  assert.equal(eth.chain, "ethereum");
  assert.equal(eth.scanned, 1);
  assert.equal(eth.totals.maybe, 1);
  assert.equal(eth.totals.yes, 0);
  assert.equal(eth.leaderboard[0].address, ADDR_A);
  assert.equal(eth.leaderboard[0].chain, "ethereum");
  const bsc = summarizeBlendRuns(rows, 100, Date.now(), "bnb");
  assert.equal(bsc.chain, "bsc");
  assert.equal(bsc.scanned, 1);
  assert.equal(bsc.totals.yes, 1);
  assert.equal(bsc.leaderboard[0].chain, "bsc");
  const all = summarizeBlendRuns(rows, 100, Date.now(), "all");
  assert.equal(all.chain, "all");
  assert.equal(all.scanned, 4);
  assert.equal(all.totals.yes, 1);
  assert.equal(all.totals.maybe, 2);
  assert.equal(all.totals.no, 1);
  assert.equal(all.leaderboard[0].chain, "bsc");
});

test("a pending slow stage is a label and does not change the heat rank", () => {
  const board = summarizeBlendRuns([
    {
      address: ADDR_A,
      heat: 4,
      blend_bucket: "maybe",
      status: "done",
      created_at: "2026-11-01T00:00:00Z",
      heat_breakdown: { score_state: "provisional", pending_stages: ["similarity", "halmos"], total: 4 },
    },
    {
      address: ADDR_B,
      heat: 9,
      blend_bucket: "yes",
      status: "done",
      created_at: "2026-11-02T00:00:00Z",
    },
  ]);
  assert.equal(board.leaderboard[0].address, ADDR_B);
  assert.equal(board.leaderboard[0].score_state, "");
  assert.equal(board.leaderboard[1].address, ADDR_A);
  assert.equal(board.leaderboard[1].heat, 4);
  assert.equal(board.leaderboard[1].score_state, "provisional");
  assert.deepEqual(board.leaderboard[1].pending_stages, ["similarity", "halmos"]);
});

test("a rescored false peak does not outrank a real historical heat", () => {
  const board = summarizeBlendRuns([
    {
      address: ADDR_A,
      heat: 12,
      blend_heat: 12,
      status: "done",
      created_at: "2026-01-01T00:00:00Z",
      heat_breakdown: { rescore: "evidence-read", peak_heat: 0, original_peak: 12 },
    },
    {
      address: ADDR_A,
      heat: 0,
      status: "done",
      created_at: "2026-11-01T00:00:00Z",
      heat_breakdown: { rescore: "evidence-read", peak_heat: 0, original_peak: 12 },
    },
    {
      address: ADDR_B,
      heat: 3,
      status: "done",
      created_at: "2026-06-01T00:00:00Z",
    },
  ]);
  assert.equal(board.leaderboard[0].address, ADDR_B);
  assert.equal(board.leaderboard[0].peak_heat, 3);
  assert.equal(board.leaderboard[1].address, ADDR_A);
  assert.equal(board.leaderboard[1].peak_heat, 0);
  assert.equal(board.leaderboard[1].heat, 0);
  assert.equal(board.leaderboard[1].original_peak, 12);
  assert.equal(board.leaderboard[0].original_peak, null);
  assert.deepEqual(board.leaderboard[0].evidence_tags, []);
});

test("evidence tags come from the breakdown and do not change heat", () => {
  const board = summarizeBlendRuns([
    {
      address: ADDR_A,
      heat: 7,
      status: "done",
      created_at: "2026-11-01T00:00:00Z",
      heat_breakdown: {
        invariants_failed: 3,
        static_evidence: 3,
        eoa_admin: 0,
        sequence: true,
        oracle: true,
        clone_evidence: 1,
        unprotected_evidence: 0,
        proxy_evidence: 2,
        fresh_evidence: 2,
        corpus_evidence: 0,
      },
    },
  ]);
  assert.equal(board.leaderboard[0].heat, 7);
  assert.deepEqual(board.leaderboard[0].evidence_tags, [
    "invariant",
    "sequence",
    "oracle",
    "static",
    "clone",
    "proxy",
    "fresh",
  ]);
});

test("a bytecode surface tag does not change the stored heat", () => {
  const board = summarizeBlendRuns([
    {
      address: ADDR_A,
      heat: 2,
      status: "done",
      heat_breakdown: { surface_evidence: 2, bytecode_surface: true },
    },
  ]);
  assert.equal(board.leaderboard[0].heat, 2);
  assert.deepEqual(board.leaderboard[0].evidence_tags, ["surface"]);
});

test("storage layout and metadata tags do not change heat", () => {
  const board = summarizeBlendRuns([
    {
      address: ADDR_A,
      heat: 3,
      status: "done",
      heat_breakdown: { static_evidence: 3, storage_layout: true, source_metadata: true, storage_slots: 4 },
    },
  ]);
  assert.equal(board.leaderboard[0].heat, 3);
  assert.deepEqual(board.leaderboard[0].evidence_tags, ["static", "layout", "metadata"]);
});

test("external suite tags do not change heat", () => {
  const board = summarizeBlendRuns([
    {
      address: ADDR_A,
      heat: 0,
      status: "done",
      heat_breakdown: { erc4626_suite: true, crytic_properties: true },
    },
  ]);
  assert.equal(board.leaderboard[0].heat, 0);
  assert.deepEqual(board.leaderboard[0].evidence_tags, ["erc4626", "properties"]);
});
