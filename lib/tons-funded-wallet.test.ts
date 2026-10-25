import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { TonsWalletDesk, tonsInFlightLabel } from "../components/tons/wallet-desk";

const desk = "zig1gy5zketezrfdea9g80we02663r2gjz3z0002kx";

function button(html: string, label: string): string {
  const match = html.match(new RegExp(`<button\\b[^>]*>${label}</button>`));
  assert.ok(match, `missing ${label} button`);
  return match[0];
}

function enabled(html: string, label: string) {
  const control = button(html, label);
  assert.equal(control.includes("disabled"), false);
  assert.equal(control.includes("aria-disabled"), false);
}

function deskView(patch: Partial<Parameters<typeof TonsWalletDesk>[0]> = {}): string {
  return renderToStaticMarkup(
    h(TonsWalletDesk, {
      localWallet: true,
      address: desk,
      sending: false,
      notice: null,
      onUseFunded: () => undefined,
      onDisconnect: () => undefined,
      ...patch,
    }),
  );
}

describe("tons desk wallet", () => {
  it("shows the desk signer on ZIGChain", () => {
    const html = deskView();
    assert.match(html, /Local wallet · ZIGChain/);
    assert.match(html, new RegExp(desk));
    assert.match(html, /Signs on the server and broadcasts on ZIGChain/);
    enabled(html, "Disconnect");
    assert.equal(html.includes("Connect wallet"), false);
    assert.equal(html.includes("Use funded wallet"), false);
    assert.match(html, new RegExp(`https://www.zigscan.org/address/${encodeURIComponent(desk)}`));
    assert.equal(tonsInFlightLabel(), "Sending");
  });

  it("holds disconnect while a send is in flight", () => {
    const html = deskView({ sending: true });
    assert.match(button(html, "Disconnect"), /disabled/);
  });

  it("offers the desk wallet again after disconnect and no other signer", () => {
    const html = deskView({ localWallet: false, notice: "The desk wallet is the only signer." });
    assert.match(html, /The desk wallet is the only signer/);
    enabled(html, "Use funded wallet");
    assert.equal(html.includes("Connect wallet"), false);
    assert.equal(html.includes("Disconnect"), false);
  });
});
