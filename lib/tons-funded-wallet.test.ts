import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Address } from "@ton/core";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  TonsWalletDesk,
  tonsInFlightLabel,
  tonsStepSendDisabled,
} from "../components/tons/wallet-desk";
import { FUNDED_WALLET_ADDRESS } from "./funded-wallet-public";
import { compileScript, type ScriptStep } from "./ton-message";

const funded = FUNDED_WALLET_ADDRESS;

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

function desk(
  patch: Partial<Parameters<typeof TonsWalletDesk>[0]> = {},
): string {
  return renderToStaticMarkup(
    h(TonsWalletDesk, {
      localWallet: false,
      restored: true,
      connected: false,
      onMainnet: false,
      address: "",
      chainName: "",
      sending: false,
      connectNotice: null,
      fundedAddress: funded,
      onUseFunded: () => undefined,
      onClearFunded: () => undefined,
      onConnect: () => undefined,
      onDisconnect: () => undefined,
      ...patch,
    }),
  );
}

describe("tons funded wallet desk", () => {
  it("offers connect and an enabled funded wallet when nothing is connected", () => {
    const html = desk();
    enabled(html, "Connect wallet");
    enabled(html, "Use funded wallet");
    assert.match(html, /Use funded wallet sends from the desk wallet without TonConnect/);
  });

  it("keeps the funded wallet available while TonConnect is still restoring", () => {
    const html = desk({ restored: false });
    assert.match(html, /Checking for a connected wallet/);
    enabled(html, "Use funded wallet");
    assert.equal(html.includes("Connect wallet"), false);
  });

  it("keeps the funded wallet available beside a connected mainnet wallet", () => {
    const html = desk({
      connected: true,
      onMainnet: true,
      address: "UQTestMainnetWallet",
    });
    assert.match(html, /Connected · mainnet/);
    assert.match(html, /UQTestMainnetWallet/);
    enabled(html, "Use funded wallet");
    enabled(html, "Disconnect");
  });

  it("keeps the funded wallet available when the connected wallet is not mainnet", () => {
    const html = desk({
      connected: true,
      onMainnet: false,
      chainName: "testnet",
    });
    assert.match(html, /This wallet is on testnet/);
    enabled(html, "Use funded wallet");
    enabled(html, "Disconnect");
  });

  it("shows the desk wallet as the connected signer and can disconnect it", () => {
    const html = desk({ localWallet: true });
    assert.match(html, /Local wallet · mainnet/);
    assert.match(html, new RegExp(funded));
    assert.match(html, /Signs on the server and broadcasts on mainnet/);
    enabled(html, "Disconnect");
    assert.equal(html.includes("Use funded wallet"), false);
    assert.equal(html.includes("Connect wallet"), false);
    assert.match(html, new RegExp(`https://tonviewer.com/${encodeURIComponent(funded)}`));
  });

  it("holds disconnect while a funded send is in flight", () => {
    const html = desk({ localWallet: true, sending: true });
    assert.match(button(html, "Disconnect"), /disabled/);
  });

  it("holds both wallet controls while a TonConnect send is in flight", () => {
    const html = desk({
      connected: true,
      onMainnet: true,
      address: "UQTestMainnetWallet",
      sending: true,
    });
    assert.match(button(html, "Use funded wallet"), /disabled/);
    assert.match(button(html, "Disconnect"), /disabled/);
  });
});

describe("tons funded signing readiness", () => {
  it("lets a step send once the funded wallet is selected", () => {
    assert.equal(
      tonsStepSendDisabled({
        sending: false,
        localWallet: true,
        restored: false,
        walletOnWrongChain: true,
      }),
      false,
    );
    assert.equal(tonsInFlightLabel(true), "Sending");
    assert.equal(tonsInFlightLabel(false), "Waiting for the wallet");
  });

  it("blocks a step send until TonConnect is restored or the chain is mainnet", () => {
    assert.equal(
      tonsStepSendDisabled({
        sending: false,
        localWallet: false,
        restored: false,
        walletOnWrongChain: false,
      }),
      true,
    );
    assert.equal(
      tonsStepSendDisabled({
        sending: false,
        localWallet: false,
        restored: true,
        walletOnWrongChain: true,
      }),
      true,
    );
    assert.equal(
      tonsStepSendDisabled({
        sending: false,
        localWallet: false,
        restored: true,
        walletOnWrongChain: false,
      }),
      false,
    );
    assert.equal(
      tonsStepSendDisabled({
        sending: true,
        localWallet: true,
        restored: true,
        walletOnWrongChain: false,
      }),
      true,
    );
  });

  it("addresses a funded send from the desk wallet", () => {
    const raw = Address.parse(funded).toRawString();
    const step: ScriptStep = {
      id: "burn",
      destination: funded,
      amount: "1",
      unit: "ton",
      bounceable: true,
      body: { kind: "empty" },
    };
    const signed = compileScript([step], { fromRaw: raw });
    assert.equal(signed.ok, true);
    if (!signed.ok) return;
    assert.equal(signed.request.from, raw);
    assert.equal(signed.request.network, "-239");

    const friendly = compileScript([step], { fromRaw: funded });
    assert.equal(friendly.ok, true);
    if (!friendly.ok) return;
    assert.equal(friendly.request.from, undefined);
  });
});
