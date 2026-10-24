"use client";

import type { ScriptStep } from "@/lib/ton-message";

const chain = [
  {
    title: "Whitelist ok",
    text: "The minter looks up the proxy id. A missing id throws before supply changes. The bounceable burn notification then returns. See step 3.",
  },
  {
    title: "Supply reduced",
    text: "The minter prices the burn, subtracts the uTON amount from total supply, and notifies the proxy.",
  },
  {
    title: "Pending withdraw deployed",
    text: "proxy_ton adds the priced TON to its debt and deploys a withdraw contract for this owner and withdraw id.",
  },
  {
    title: "Wait for the time lock",
    text: "That contract stores withdraw_timestamp as the burn time plus withdraw_pending_time on proxy_ton. The published unstake wait is 3 days. The source keeps the duration on the proxy, not as a constant.",
  },
] as const;

export function ProxyBurnDesk({
  burn,
  notification,
  pendingAddress,
  onPendingAddress,
}: {
  burn: ScriptStep;
  notification: ScriptStep;
  pendingAddress: string;
  onPendingAddress: (value: string) => void;
}) {
  const queryId = paired(fieldValue(burn, "query_id"), fieldValue(notification, "query_id"));
  const proxyId = paired(fieldValue(burn, "proxy_id"), fieldValue(notification, "proxy_id"));
  const withdrawId = fieldValue(notification, "withdraw_id").trim();
  const owner = fieldValue(notification, "owner").trim();

  return (
    <section className="ton-step" id="proxy-burn-form" aria-labelledby="step-4-title">
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">Step 4 · Proxy burn</p>
          <h2 id="step-4-title">Proxy burn and pending withdraw</h2>
        </div>
      </div>
      <p className="ton-section-copy">
        After step 3 is accepted, the minter runs proxy_burn and the proxy
        deploys a pending withdraw. The minter sends opcode 0x1004 to the
        proxy. The proxy initializes the new contract with opcode 0x4501.
        Neither opcode is a user message.
      </p>

      <label className="ton-field">
        <span>Query id</span>
        <input readOnly value={queryId.text} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">
        64 bits from steps 2 and 3. The minter copies this query id onto the
        message to the proxy, and the proxy copies it into the init message.
        {queryId.note}
      </p>

      <label className="ton-field">
        <span>Withdraw id</span>
        <input readOnly value={withdrawId} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">
        64 bits from step 3. The wallet sets this from withdraw_cnt when it
        burns, then the pending contract is deployed for this id.
      </p>

      <label className="ton-field">
        <span>Proxy id</span>
        <input readOnly value={proxyId.text} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">
        32 bits from steps 2 and 3. The minter checks this id on the whitelist.
        The pending withdraw does not store it.
        {proxyId.note}
      </p>

      <label className="ton-field">
        <span>Owner</span>
        <input readOnly value={owner} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">From step 3. The pending withdraw is deployed for this owner.</p>

      <label className="ton-field" htmlFor="pending-withdraw-address">
        <span>Pending withdraw address</span>
        <input
          id="pending-withdraw-address"
          value={pendingAddress}
          onChange={(event) => onPendingAddress(event.target.value)}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder="Paste when known"
        />
      </label>
      <p className="ton-hint">
        Derived from the owner, withdraw id, proxy_ton, the minter, and the
        withdraw code. Paste it when you already have it. This page does not
        derive it.
      </p>

      <p className="ton-section-copy">
        Time lock: withdraw_timestamp is the burn timestamp plus
        withdraw_pending_time on proxy_ton. That duration is storage on the
        proxy. The published unstake wait is 3 days. This page does not read
        the proxy.
      </p>

      <label className="ton-field">
        <span>Finished at deploy</span>
        <input readOnly value="0" />
      </label>
      <p className="ton-hint">
        1 bit. The state init stores 0. get_withdraw_data returns the flag with
        the withdraw data. Not read from the chain.
      </p>

      <ol className="ton-flow" aria-label="After a successful burn notification">
        {chain.map((item, index) => (
          <li key={item.title}>
            <span className="ton-flow-index">{index + 1}</span>
            <div>
              <h3>{item.title}</h3>
              <p>{item.text}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="ton-hint">A static list of the contract steps. Not a chain read.</p>
      <p className="ton-hint">
        This leg is contract-to-contract after step 3. There is no user message
        to send here.
      </p>
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
    text: `Step 2 ${left || "—"} · Step 3 ${right || "—"}`,
    note: " Step 2 and step 3 differ.",
  };
}
