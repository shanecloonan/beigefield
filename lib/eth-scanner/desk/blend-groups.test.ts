import assert from "node:assert/strict";
import test from "node:test";
import { groupByEngineRule } from "./blend-groups";

test("four engines on one rule collapse to four group rows with a full agreement score", () => {
  const groups = groupByEngineRule([
    {
      engine: "medusa",
      rule: "no_third_party_balance_drop",
      kind: "drain-proof",
      label: "drain proof",
      agreement_score: 1,
      agreement_count: 4,
      engines_agreeing: ["ityfuzz", "halmos", "medusa", "echidna"],
      severity: "high",
      title: "Caller-profit drain proof",
    },
  ]);
  assert.equal(groups.length, 4);
  assert.ok(groups.every((row) => row.agreement_score === 1 && row.label === "drain proof"));
  assert.deepEqual(
    groups.map((row) => row.engine).sort(),
    ["echidna", "halmos", "ityfuzz", "medusa"],
  );
});

test("a solvency miss is evidence only", () => {
  const groups = groupByEngineRule([
    { engine: "halmos", rule: "solvency", kind: "evidence-only", severity: "info", title: "evidence" },
  ]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].label, "evidence only");
  assert.equal(groups[0].agreement_score, 0.25);
});
