import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AutomationGap } from "../components/tons/automation-gap";
import { BounceDesk } from "../components/tons/bounce-desk";
import { PathRunBar } from "../components/tons/path-run-bar";
import { PayoutDesk } from "../components/tons/payout-desk";
import { ScriptStepCard } from "../components/tons/script-step";
import type { ScriptStep } from "./ton-message";
import { automationSource } from "./uton-automation";
import { utonTemplateBody, utonTemplateById } from "./uton-templates";

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
    const bounce = renderToStaticMarkup(
      h(BounceDesk, {
        sending: false,
        sendLabel: "Send",
        disabled: false,
        notice: null,
        onSend: () => undefined,
      }),
    );
    const payout = renderToStaticMarkup(
      h(PayoutDesk, {
        sending: false,
        sendLabel: "Send",
        disabled: false,
        notice: null,
        onSend: () => undefined,
      }),
    );
    const gap = renderToStaticMarkup(
      h(AutomationGap, {
        id: "after-burn-1",
        titleId: "after-burn-1-title",
        kicker: "After step 1",
        title: "afterBurn1",
        sources: [automationSource.afterBurn1],
        hint: "afterBurn1 queues the redeem burn, the redeem notification, and the withdraw once bounce is on the path. Send broadcasts those three messages on mainnet. A sent message is final.",
        sending: false,
        sendLabel: "Send",
        disabled: false,
        notice: null,
        onSend: () => undefined,
      }),
    );
    const next = renderToStaticMarkup(
      h(AutomationGap, {
        id: "queue-after-bounce",
        titleId: "queue-after-bounce-title",
        kicker: "After step 3",
        title: "nextAfter",
        sources: [automationSource.queueAfterBounce],
        hint: "nextAfter names the redeem burn after the bounce. Send broadcasts that burn on mainnet. A sent message is final.",
        sending: false,
        sendLabel: "Send",
        disabled: false,
        notice: null,
        onSend: () => undefined,
      }),
    );
    for (const html of [bounce, payout, gap, next]) {
      const button = sendButton(html, "Send");
      assert.equal(button.includes("disabled"), false);
      assert.equal(button.includes("aria-disabled"), false);
    }
    assert.doesNotMatch(bounce, /on_bounce runs on the jetton wallet/);
    assert.match(gap, /broadcasts those three messages/);
    assert.match(next, /broadcasts that burn/);
    assert.match(payout, /0x1001/);
    assert.match(payout, /0x1002/);
    assert.doesNotMatch(gap, /It is not a wallet message/);
    assert.doesNotMatch(payout, /Nothing was sent\. query_ack runs between/);
  });

  it("shows bounce send progress and the broadcast result", () => {
    const sending = renderToStaticMarkup(
      h(BounceDesk, {
        sending: true,
        sendLabel: "Sending",
        disabled: true,
        notice: null,
        onSend: () => undefined,
      }),
    );
    const button = sendButton(sending, "Sending");
    assert.match(button, /disabled/);
    assert.match(button, /aria-busy="true"/);
    assert.match(sending, /role="status"/);

    const rejected = renderToStaticMarkup(
      h(BounceDesk, {
        sending: false,
        sendLabel: "Send",
        disabled: false,
        notice: {
          tone: "bad",
          text: "The network rejected the message. Nothing was sent.",
        },
        onSend: () => undefined,
      }),
    );
    assert.match(rejected, /The network rejected the message\. Nothing was sent\./);
    assert.doesNotMatch(rejected, /on_bounce runs on the jetton wallet/);

    const queued = renderToStaticMarkup(
      h(AutomationGap, {
        id: "after-burn-1",
        titleId: "after-burn-1-title",
        kicker: "After step 1",
        title: "afterBurn1",
        sources: [automationSource.afterBurn1],
        hint: "queued",
        sending: false,
        sendLabel: "Send",
        disabled: false,
        notice: {
          tone: "good",
          text: "Sent the queued path on mainnet.",
          href: "https://tonviewer.com/EQAfF5j3JMIpZlLmACv7Ub7RH7WmiVMuV4ivcgNYHvNnqHTz",
          hrefLabel: "View the destination on Tonviewer",
        },
        onSend: () => undefined,
      }),
    );
    assert.match(queued, /Sent the queued path on mainnet\./);
    assert.match(queued, /href="https:\/\/tonviewer.com\//);
  });

  it("renders one Run path control and explains the jetton wallet and the pending withdraw", () => {
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
    const button = sendButton(html, "Run path");
    assert.equal(button.includes("disabled"), false);
    assert.match(button, /ton-button-lead/);
    assert.match(html, /burn notification/);
    assert.match(html, /pending withdraw|contract address/);

    const burnTemplate = utonTemplateById("uton-burn");
    const withdrawTemplate = utonTemplateById("withdraw");
    assert.ok(burnTemplate && withdrawTemplate);
    const burnStep: ScriptStep = {
      ...draft,
      body: utonTemplateBody(burnTemplate),
    };
    const withdrawStep: ScriptStep = {
      ...draft,
      id: "withdraw",
      body: utonTemplateBody(withdrawTemplate),
    };
    const burn = renderToStaticMarkup(
      h(ScriptStepCard, {
        index: 0,
        total: 5,
        step: burnStep,
        showErrors: false,
        sending: false,
        sendLabel: "Send burn",
        sendDisabled: false,
        place: {
          anchor: "burn-form",
          kicker: "Step 1",
          title: "burn_tokens",
          sources: [],
          destinationNote:
            "This is your uTON jetton wallet: the address that holds your uTON. The minter calculates it from the wallet you connect.",
        },
        onChange: () => undefined,
        onMove: () => undefined,
        onRemove: () => undefined,
        onSend: () => undefined,
      }),
    );
    assert.match(burn, /Calculated from the wallet that sends/);
    assert.match(burn, /uTON jetton wallet/);
    assert.doesNotMatch(burn, /Paste your uTON/);

    const withdraw = renderToStaticMarkup(
      h(ScriptStepCard, {
        index: 4,
        total: 5,
        step: withdrawStep,
        showErrors: false,
        sending: false,
        sendLabel: "Send withdraw",
        sendDisabled: false,
        place: {
          anchor: "withdraw-form",
          kicker: "Step 6",
          title: "withdraw_ton",
          sources: [],
          destinationNote:
            "The pending withdraw contract is created when a listed proxy accepts a burn. Paste that contract here after it exists.",
        },
        onChange: () => undefined,
        onMove: () => undefined,
        onRemove: () => undefined,
        onSend: () => undefined,
      }),
    );
    assert.match(withdraw, /Created after a listed burn/);
    assert.match(withdraw, /pending withdraw contract/);
  });
});
