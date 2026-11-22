import assert from "node:assert/strict";
import test from "node:test";
import { summarizeSiteHits } from "./board.ts";

test("the board keeps the all-time peak and the latest heat", () => {
  const rows = summarizeSiteHits([
    { host: "a.example", heat: 2, peak_heat: 9, updated_at: "2026-01-01T00:00:00Z", findings: [{ id: "missing-csp", title: "No CSP", evidence: "none", remediation: "Send CSP." }] },
    { host: "a.example", heat: 4, peak_heat: 4, updated_at: "2026-02-01T00:00:00Z" },
    { host: "b.example", heat: 6, peak_heat: 6, updated_at: "2026-02-01T00:00:00Z" },
  ]);
  assert.equal(rows[0].host, "a.example");
  assert.equal(rows[0].heat, 4);
  assert.equal(rows[0].peak_heat, 9);
  assert.equal(rows[1].host, "b.example");
  assert.equal(rows.length, 2);
});
