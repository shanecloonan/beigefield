import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SolWalletDesk, solInFlightLabel } from "../components/sol/wallet-desk";
import { PathCards } from "../components/sol/sol-composer";
import { KatanaNotes } from "../components/sol/katana-notes";
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

function deskView(patch: Partial<Parameters<typeof SolWalletDesk>[0]> = {}): string {
  return renderToStaticMarkup(
    h(SolWalletDesk, {
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

describe("sol desk wallet", () => {
  it("shows the desk signer on Solana", () => {
    const html = deskView();
    assert.match(html, /Desk wallet · Solana/);
    assert.match(html, new RegExp(SOL_FUNDED_WALLET_ADDRESS));
    assert.match(html, /Signs on the server and broadcasts on Solana mainnet/);
    enabled(html, "Disconnect");
    assert.equal(html.includes("Connect wallet"), false);
    assert.equal(html.includes("Use funded wallet"), false);
    assert.match(html, new RegExp(`https://solscan.io/account/${SOL_FUNDED_WALLET_ADDRESS}`));
    assert.equal(solInFlightLabel(), "Sending");
    assert.equal(html.includes("UTONIC"), false);
    assert.equal(html.includes("Valdora"), false);
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

describe("sol path cards", () => {
  it("lists remaining Katana instructions and omits other protocols", () => {
    const html = renderToStaticMarkup(h(PathCards));
    assert.match(html, /claim_shares/);
    assert.match(html, /withdraw_expired/);
    assert.match(html, /complete_withdraw/);
    assert.match(html, /instant_withdraw/);
    assert.match(html, /deposit is omitted/);
    assert.match(html, /migrate is omitted/);
    assert.equal(html.includes("UTONIC"), false);
    assert.equal(html.includes("uTON"), false);
    assert.equal(html.includes("Valdora"), false);
    assert.equal(html.includes("Jupiter"), false);
    assert.equal(html.includes("pump.fun"), false);
  });

  it("states the Katana programs and the PsyFi shutdown", () => {
    const html = renderToStaticMarkup(h(KatanaNotes));
    assert.match(html, /1349iiGjWC7ZTbu6otFmJwztms122jEEnShKgpVnNewy/);
    assert.match(html, /7h7uYbDBZkiTvWLmMsWNAEs2VVNqfV56uSfP9hbjJMP8/);
    assert.match(html, /1 May 2025/);
    assert.equal(html.includes("UTONIC"), false);
  });
});
