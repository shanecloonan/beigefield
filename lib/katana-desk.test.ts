import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { KatanaComposer } from "../components/katana/katana-composer";
import { KatanaAuthorizedNotes } from "../components/katana/katana-notes";
import { KatanaWalletDesk, katanaInFlightLabel } from "../components/katana/wallet-desk";
import { WithdrawBar } from "../components/katana/withdraw-bar";
import { SOL_FUNDED_WALLET_ADDRESS } from "./sol-funded-wallet-public";

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

function labels(html: string): string[] {
  return [...html.matchAll(/<button\b[^>]*>([^<]*)<\/button>/g)].map((match) => match[1] ?? "");
}

function deskView(patch: Partial<Parameters<typeof KatanaWalletDesk>[0]> = {}): string {
  return renderToStaticMarkup(
    h(KatanaWalletDesk, {
      localWallet: true,
      address: SOL_FUNDED_WALLET_ADDRESS,
      sending: false,
      notice: null,
      onUseFunded: () => undefined,
      onDisconnect: () => undefined,
      ...patch,
    }),
  );
}

describe("katana desk wallet", () => {
  it("shows the desk signer on Solana", () => {
    const html = deskView();
    assert.match(html, /Desk wallet · Solana/);
    assert.match(html, new RegExp(SOL_FUNDED_WALLET_ADDRESS));
    assert.match(html, /Signs on the server and broadcasts on Solana mainnet/);
    enabled(html, "Disconnect");
    assert.equal(html.includes("Connect wallet"), false);
    assert.equal(html.includes("Use funded wallet"), false);
    assert.match(html, new RegExp(`https://solscan.io/account/${SOL_FUNDED_WALLET_ADDRESS}`));
    assert.equal(katanaInFlightLabel(), "Sending");
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

  it("autoconnects the desk wallet and fills only destination from that address", () => {
    const page = renderToStaticMarkup(h(KatanaComposer, { deskAddress: SOL_FUNDED_WALLET_ADDRESS }));
    assert.deepEqual(labels(page).sort(), ["Copy address", "Disconnect", "Withdraw pending deposit"]);
    assert.match(button(page, "Withdraw pending deposit"), /disabled/);
    assert.equal(page.includes("Connect wallet"), false);
    assert.equal(page.includes("Connect a Solana browser wallet"), false);
    assert.match(page, /Desk wallet · Solana/);
    assert.match(page, new RegExp(SOL_FUNDED_WALLET_ADDRESS));
    assert.match(
      page,
      new RegExp(`aria-label="Destination token account"[^>]*value="${SOL_FUNDED_WALLET_ADDRESS}"`),
    );
    assert.match(page, /aria-label="User authority"/);
    const authority = page.match(/aria-label="User authority"[^>]*>/);
    assert.ok(authority);
    assert.equal(authority[0].includes(SOL_FUNDED_WALLET_ADDRESS), false);
  });
});

describe("katana authorized desk", () => {
  it("states authorized withdraw copy without path or outsider language", () => {
    const notes = renderToStaticMarkup(h(KatanaAuthorizedNotes));
    assert.match(notes, /Withdraw pending deposit/);
    assert.match(notes, /desk wallet is the fee payer/);
    assert.match(notes, /signs on the server/);
    assert.match(notes, /separately/);
    assert.match(notes, /claim_shares/);
    assert.match(notes, /DkguYGWhRE8qJ9voWNYZ8dJkGYr8ACUR8KXqDAyHpGx2/);
    assert.match(notes, /CPFuWtS7qNQt3RPnSt5opKph9JbqdW3LjxF1HEw3v1tP/);
    assert.match(notes, /destination/);
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
    assert.match(bar, /desk wallet is the fee payer/);
    assert.match(button(bar, "Withdraw pending deposit"), /disabled/);
  });
});
