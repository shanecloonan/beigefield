import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AutomationGap } from "../components/tons/automation-gap";
import { BounceDesk } from "../components/tons/bounce-desk";
import { PayoutDesk } from "../components/tons/payout-desk";
import { ScriptStepCard } from "../components/tons/script-step";
import type { ScriptStep } from "./ton-message";
import { automationSource } from "./uton-automation";

const draft: ScriptStep = {
  id: "burn",
  destination: "",
  amount: "",
  unit: "ton",
  bounceable: true,
  body: { kind: "empty" },
};

function sendButton(html: string, label: string): string {
  const match = html.match(new RegExp(`<button\\b[^>]*>${label}</button>`));
  assert.ok(match, `missing ${label} button`);
  return match[0];
}

describe("tons send buttons", () => {
  it("renders a step Send button that can run its handler", () => {
    const html = renderToStaticMarkup(
      h(ScriptStepCard, {
        index: 0,
        total: 1,
        step: draft,
        showErrors: true,
        errors: { destination: "Enter a destination address.", amount: "Enter a value." },
        sending: false,
        sendLabel: "Send burn",
        sendDisabled: false,
        onChange: () => undefined,
        onMove: () => undefined,
        onRemove: () => undefined,
        onSend: () => undefined,
        status: h("p", { role: "status" }, "Nothing was sent. Connect a mainnet wallet first."),
      }),
    );
    const button = sendButton(html, "Send burn");
    assert.equal(button.includes("disabled"), false);
    assert.equal(button.includes("aria-disabled"), false);
    assert.match(html, /Enter a destination address\./);
    assert.match(html, /Nothing was sent\. Connect a mainnet wallet first\./);
  });

  it("disables a step Send button only while a send is in flight", () => {
    const html = renderToStaticMarkup(
      h(ScriptStepCard, {
        index: 0,
        total: 1,
        step: draft,
        showErrors: false,
        sending: true,
        sendLabel: "Waiting for the wallet",
        sendDisabled: true,
        onChange: () => undefined,
        onMove: () => undefined,
        onRemove: () => undefined,
        onSend: () => undefined,
      }),
    );
    const button = sendButton(html, "Waiting for the wallet");
    assert.match(button, /disabled/);
  });

  it("renders the path Send buttons as enabled controls", () => {
    const bounce = renderToStaticMarkup(h(BounceDesk));
    const payout = renderToStaticMarkup(h(PayoutDesk));
    const gap = renderToStaticMarkup(
      h(AutomationGap, {
        id: "after-burn-1",
        titleId: "after-burn-1-title",
        kicker: "After step 1",
        title: "afterBurn1",
        sources: [automationSource.afterBurn1],
        detail: "Nothing was sent. afterBurn1 watches the path. It is not a wallet message.",
      }),
    );
    for (const html of [bounce, payout, gap]) {
      const button = sendButton(html, "Send");
      assert.equal(button.includes("disabled"), false);
      assert.equal(button.includes("aria-disabled"), false);
    }
  });
});
