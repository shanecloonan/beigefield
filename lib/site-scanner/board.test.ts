import assert from "node:assert/strict";
import test from "node:test";
import { summarizeSiteHits } from "./board.ts";

test("the board keeps the all-time peak beside the latest heat", () => {
  const rows = summarizeSiteHits([
    { host: "a.example", heat: 2, peak_heat: 9, updated_at: "2026-01-01T00:00:00Z", findings: [{ id: "missing-csp", title: "No CSP", evidence: "none", remediation: "Send CSP." }] },
    { host: "a.example", heat: 4, peak_heat: 4, updated_at: "2026-02-01T00:00:00Z" },
    { host: "b.example", heat: 6, peak_heat: 6, updated_at: "2026-02-01T00:00:00Z" },
  ]);
  assert.equal(rows[0].host, "b.example");
  assert.equal(rows[0].heat, 6);
  assert.equal(rows[1].host, "a.example");
  assert.equal(rows[1].heat, 4);
  assert.equal(rows[1].peak_heat, 9);
});

test("header hygiene does not outrank a real exposure", () => {
  const rows = summarizeSiteHits([
    {
      host: "headers.example",
      heat: 5,
      peak_heat: 5,
      findings: [
        { id: "missing-csp", title: "No Content-Security-Policy", heat: 3 },
        { id: "missing-hsts", title: "No Strict-Transport-Security", heat: 2 },
      ],
    },
    {
      host: "leak.example",
      heat: 5,
      peak_heat: 5,
      findings: [{ id: "secret-in-page", title: "A secret-shaped token is in a public response", heat: 5 }],
    },
  ]);
  assert.equal(rows[0].host, "leak.example");
  assert.equal(rows[0].heat, 8);
  assert.equal(rows[1].host, "headers.example");
  assert.equal(rows[1].heat, 1);
  assert.equal(rows[1].findings.length, 2);
});
