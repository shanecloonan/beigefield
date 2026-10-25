import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PathRunBar } from "../components/tons/path-run-bar";
import { PathCards, ZigComposer } from "../components/tons/zig-composer";

const desk = "zig1gy5zketezrfdea9g80we02663r2gjz3z0002kx";

function button(html: string, label: string): string {
  const match = html.match(new RegExp(`<button\\b[^>]*>${label}</button>`));
  assert.ok(match, `missing ${label} button`);
  return match[0];
}

function labels(html: string): string[] {
  return [...html.matchAll(/<button\b[^>]*>([^<]*)<\/button>/g)].map((match) => match[1] ?? "");
}

describe("tons run path control", () => {
  it("keeps Run path as the only enabled lead control", () => {
    const html = renderToStaticMarkup(
      h(PathRunBar, {
        sending: false,
        label: "Run path",
        disabled: false,
        notice: null,
        lookupNote: null,
        onRun: () => undefined,
      }),
    );
    const lead = button(html, "Run path");
    assert.equal(lead.includes("disabled"), false);
    assert.match(lead, /ton-button-lead/);
    assert.match(html, /MsgExecuteContract/);
    assert.match(html, /withdraw_unbonded_by_id/);
    assert.match(html, /LCD/);
    assert.deepEqual(labels(html), ["Run path"]);
  });

  it("disables Run path while a send is in flight and links a broadcast", () => {
    const sending = renderToStaticMarkup(
      h(PathRunBar, {
        sending: true,
        label: "Sending",
        disabled: true,
        notice: null,
        lookupNote: "LCD paused=false total_count=54 suggested_id=12.",
        onRun: () => undefined,
      }),
    );
    const lead = button(sending, "Sending");
    assert.match(lead, /disabled/);
    assert.match(lead, /aria-busy="true"/);
    assert.match(sending, /suggested_id=12/);

    const done = renderToStaticMarkup(
      h(PathRunBar, {
        sending: false,
        label: "Run path",
        disabled: false,
        notice: {
          tone: "good",
          text: "Broadcast ab at height 9.",
          href: "https://www.zigscan.org/tx/ab",
          hrefLabel: "View the transaction",
        },
        lookupNote: null,
        onRun: () => undefined,
      }),
    );
    assert.match(done, /href="https:\/\/www.zigscan.org\/tx\/ab"/);
    assert.match(done, /View the transaction/);
  });

  it("renders the path cards with no Send control", () => {
    const cards = renderToStaticMarkup(h(PathCards));
    assert.equal(cards.includes("<button"), false);
    assert.match(cards, /total_completed_unbondings/);
    assert.match(cards, /withdraw_unbonded_by_id/);
    assert.match(cards, /completed_unbondings/);
    assert.match(cards, /id="query-totals"/);
    assert.match(cards, /id="execute"/);
    assert.match(cards, /id="handler"/);

    const page = renderToStaticMarkup(h(ZigComposer, { deskAddress: desk }));
    assert.deepEqual(labels(page).sort(), ["Copy address", "Disconnect", "Run path"]);
    assert.match(button(page, "Run path"), /disabled/);
    assert.equal(/Connect wallet|TonConnect|tonconnect|>Send</i.test(page), false);
    assert.match(page, /Local wallet · ZIGChain/);
    assert.match(page, new RegExp(desk));
  });
});
