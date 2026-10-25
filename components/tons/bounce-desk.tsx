"use client";

import type { ScriptStep } from "@/lib/ton-message";
import { UTON_OP } from "@/lib/uton-templates";

const reads = [
  {
    title: "Skip the bounce prefix",
    text: "on_bounce drops the first 32 bits. A bounced body starts with 0xFFFFFFFF, then the original message.",
  },
  {
    title: "Accept this opcode",
    text: "The handler accepts an internal transfer or a burn notification. The bounced notification carries the burn-notification opcode.",
  },
  {
    title: "Query id, then coins",
    text: "It loads a 64-bit query id, then load_coins(). On an internal transfer that coin slot is the uTON amount. On this notification the owner address sits there, and the uTON amount comes later.",
  },
  {
    title: "Credit, and leave the counter",
    text: "The coin read is added to balance. burn_tokens already incremented withdraw_cnt. on_bounce does not reduce it. The source notes that the counter cannot be reduced here.",
  },
] as const;

export function BounceDesk({
  burn,
  notification,
}: {
  burn: ScriptStep;
  notification: ScriptStep;
}) {
  const proxyId = paired(fieldValue(burn, "proxy_id"), fieldValue(notification, "proxy_id"));
  const queryId = paired(fieldValue(burn, "query_id"), fieldValue(notification, "query_id"));
  const owner = fieldValue(notification, "owner").trim();
  const amount = fieldValue(notification, "amount").trim();
  const withdrawId = fieldValue(notification, "withdraw_id").trim();

  return (
    <section className="ton-step" id="bounce-form" aria-labelledby="step-3-title">
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">Step 3 · on_bounce</p>
          <h2 id="step-3-title">Bounced notification, misread</h2>
        </div>
      </div>
      <p className="ton-section-copy">
        The minter throws on proxy id 3 before it changes supply, so the
        bounceable notification from step 2 returns to the jetton wallet.
        recv_internal sees the bounced flag and calls on_bounce. This step is
        not a user message.
      </p>

      <label className="ton-field">
        <span>Opcode</span>
        <input readOnly value={UTON_OP.burnNotification} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">Burn notification. on_bounce accepts this opcode or an internal transfer.</p>

      <label className="ton-field">
        <span>Proxy id</span>
        <input readOnly value={proxyId.text} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">
        32 bits from steps 1 and 2. The minter looked this id up and threw.
        on_bounce does not read it.
        {proxyId.note}
      </p>

      <label className="ton-field">
        <span>Query id</span>
        <input readOnly value={queryId.text} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">
        64 bits. on_bounce loads this and does not store it.
        {queryId.note}
      </p>

      <label className="ton-field">
        <span>Owner address, in the coin slot</span>
        <input readOnly value={owner} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">
        Step 2 stores the owner here, before the withdraw id and the uTON
        amount. on_bounce calls load_coins() on this slot and adds that read
        to balance. This page does not parse the address as coins.
      </p>

      <label className="ton-field">
        <span>uTON amount</span>
        <input readOnly value={amount} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">
        The amount step 2 stored after the withdraw id. on_bounce does not read this field.
      </p>

      <label className="ton-field">
        <span>Withdraw id</span>
        <input readOnly value={withdrawId} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">
        burn_tokens copied withdraw_cnt, then incremented the counter. on_bounce leaves it.
      </p>

      <ol className="ton-flow" aria-label="What on_bounce does with the bounced notification">
        {reads.map((item, index) => (
          <li key={item.title}>
            <span className="ton-flow-index">{index + 1}</span>
            <div>
              <h3>{item.title}</h3>
              <p>{item.text}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="ton-hint">A reading of wallet.func. Not a chain read, and not a second credit computed here.</p>
      <button type="button" className="ton-button" disabled aria-disabled="true">
        Send
      </button>
      <p className="ton-hint">Locked. The bounce is the chain returning step 2. Pressing Send does nothing.</p>
    </section>
  );
}

function fieldValue(step: ScriptStep, id: string): string {
  if (step.body.kind !== "fields") return "";
  return step.body.fields.find((field) => field.id === id)?.value ?? "";
}

function paired(leftRaw: string, rightRaw: string): { text: string; note: string } {
  const left = leftRaw.trim();
  const right = rightRaw.trim();
  if (left === right) return { text: left, note: "" };
  return {
    text: `Step 1 ${left || "—"} · Step 2 ${right || "—"}`,
    note: " Step 1 and step 2 differ.",
  };
}
