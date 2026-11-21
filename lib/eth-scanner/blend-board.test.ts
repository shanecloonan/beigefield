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

test("a collapsed outflow is flagged and kept off the heat ranking", () => {
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
  assert.equal(board.leaderboard.length, 1);
  assert.equal(board.leaderboard[0].address, ADDR_B);
  assert.equal(board.flagged.length, 1);
  assert.equal(board.flagged[0].address, ADDR_A);
  assert.equal(board.flagged[0].liveness, "already-exploited");
});

test("the rank uses the latest heat and keeps the historical peak", () => {
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
  assert.equal(board.leaderboard[0].address, ADDR_B);
  assert.equal(board.leaderboard[0].heat, 4);
  assert.equal(board.leaderboard[1].address, ADDR_A);
  assert.equal(board.leaderboard[1].heat, 1);
  assert.equal(board.leaderboard[1].peak_heat, 9);
  assert.equal(board.leaderboard[1].history_count, 2);
  assert.equal(board.leaderboard[1].stale, false);
  assert.equal(board.requeue.length, 1);
  assert.equal(board.requeue[0].address, ADDR_B);
  assert.equal(board.requeue[0].peak_heat, 4);
});
