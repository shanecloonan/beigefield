import assert from "node:assert/strict";
import test from "node:test";
import { summarizeRuns, summarizeSiteHits } from "./board.ts";

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

test("a host keeps its tech stack and an end-of-life library adds heat", () => {
  const rows = summarizeSiteHits([
    {
      host: "lib.example",
      heat: 1,
      peak_heat: 1,
      heat_breakdown: {
        tech: [
          { name: "jQuery", version: "1.12.4", source: "script", eol: true },
          { name: "Nginx", version: "1.24.0", source: "headers", eol: false },
          { name: "  ", version: "1" },
        ],
      },
      findings: [{ id: "known-eol", title: "A detected library is a known end-of-life release", evidence: "jQuery 1.12.4", remediation: "Upgrade.", stage: "fingerprint" }],
    },
  ]);
  assert.equal(rows[0].heat, 4);
  assert.equal(rows[0].tech.length, 2);
  assert.equal(rows[0].tech[0].name, "jQuery");
  assert.equal(rows[0].tech[0].eol, true);
  assert.equal(rows[0].tech[1].eol, false);
  assert.equal(rows[0].findings[0].evidence, "jQuery 1.12.4");
});

test("run history keeps counts and drops a row without an id", () => {
  const runs = summarizeRuns([
    { run_id: "101", started_at: "2026-11-25T04:00:00Z", finished_at: "2026-11-25T04:02:00Z", hosts_scanned: 6, finding_count: 3 },
    { run_id: "", hosts_scanned: 9 },
    { hosts_scanned: 4 },
  ]);
  assert.equal(runs.length, 1);
  assert.equal(runs[0].hosts_scanned, 6);
  assert.equal(runs[0].finding_count, 3);
});
