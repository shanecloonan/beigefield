import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { KatanaAuthorizedNotes } from "../components/katana/katana-notes";
import { KatanaWalletDesk } from "../components/katana/wallet-desk";
import { WithdrawBar } from "../components/katana/withdraw-bar";
import { SOL_FUNDED_WALLET_ADDRESS } from "./sol-funded-wallet-public";

function button(html: string, label: string): string {
  const match = html.match(new RegExp(`<button\\b[^>]*>${label}</button>`));
  assert.ok(match, `missing ${label} button`);
  return match[0];
}

describe("katana authorized desk", () => {
  it("asks the browser wallet to connect and does not mention a desk signer", () => {
    const html = renderToStaticMarkup(
      h(KatanaWalletDesk, {
        address: null,
        connecting: false,
        sending: false,
        notice: null,
        onConnect: () => undefined,
        onDisconnect: () => undefined,
      }),
    );
    assert.match(html, /Connect wallet/);
    assert.equal(html.includes("Use funded wallet"), false);
    assert.equal(html.includes("desk"), false);
    assert.equal(html.includes("Desk wallet"), false);
  });

  it("shows the connected wallet and requires that wallet to sign", () => {
    const html = renderToStaticMarkup(
      h(KatanaWalletDesk, {
        address: SOL_FUNDED_WALLET_ADDRESS,
        connecting: false,
        sending: false,
        notice: null,
        onConnect: () => undefined,
        onDisconnect: () => undefined,
      }),
    );
    assert.match(html, new RegExp(SOL_FUNDED_WALLET_ADDRESS));
    assert.match(html, /Connected wallet must sign/);
    assert.match(html, /Disconnect/);
    assert.equal(html.includes("Signs on the server"), false);
    assert.match(button(html, "Disconnect"), /./);
  });

  it("states authorized withdraw copy without path or outsider language", () => {
    const notes = renderToStaticMarkup(h(KatanaAuthorizedNotes));
    assert.match(notes, /Withdraw pending deposit/);
    assert.match(notes, /connected wallet must sign/);
    assert.match(notes, /associated token account/);
    assert.match(notes, /1349iiGjWC7ZTbu6otFmJwztms122jEEnShKgpVnNewy/);
    assert.equal(notes.includes("path"), false);
    assert.equal(notes.includes("attacker"), false);
    assert.equal(notes.includes("exploit"), false);
    const bar = renderToStaticMarkup(
      h(WithdrawBar, {
        sending: false,
        label: "Withdraw pending deposit",
        disabled: true,
        notice: null,
        lookupNote: "Vault round 63. This wallet has no Katana user account on this vault.",
        onRun: () => undefined,
      }),
    );
    assert.match(bar, /Withdraw pending deposit/);
    assert.match(bar, /same-round pending deposit/);
    assert.match(button(bar, "Withdraw pending deposit"), /disabled/);
  });
});
