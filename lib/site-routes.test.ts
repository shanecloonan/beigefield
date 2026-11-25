import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

function read(path: string): string {
  return readFileSync(new URL(path, import.meta.url), "utf8");
}

describe("homepage routes", () => {
  it("offers Blockchain and leaves /blend in place", () => {
    const home = read("../app/page.tsx");
    assert.match(home, /href="\/blend"/);
    assert.match(home, />Blockchain</);
    assert.equal(home.includes('href="/scan"'), false);
    assert.equal(home.includes(">Web<"), false);
    assert.equal(home.includes('href="/eth"'), false);
    assert.equal(home.includes('href="/sol"'), false);
    assert.equal(home.includes(">Ethereum<"), false);
    assert.equal(home.includes(">Solana<"), false);
    assert.match(read("../app/blend/page.tsx"), /BlendApp/);
    assert.equal(read("../next.config.ts").includes('source: "/blend"'), false);
  });
});
