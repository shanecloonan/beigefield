"use client";

import type { ScriptStep } from "@/lib/ton-message";
import { utonMinter } from "@/lib/uton";

const chain = [
  {
    title: "query_data",
    text: "The pending withdraw sends opcode 0x1001 to the minter. The reference carries the recipient and the response address from step 5.",
  },
  {
    title: "query_ack",
    text: "The minter answers that caller with opcode 0x1002. The body carries supply, price, and the price increment. This page does not read those values.",
  },
  {
    title: "Re-price",
    text: "A later price can only lower the TON to be paid. If the new amount is smaller, the contract stores it. A higher price leaves the stored amount as it was.",
  },
  {
    title: "Notify proxy",
    text: "The contract sets finished to 1, then sends opcode 0x4004 to proxy_ton. A bounce of that notification clears finished.",
  },
  {
    title: "TON transfer",
    text: "proxy_ton checks the sender, reduces its debt, and sends the TON to the recipient.",
  },
] as const;

export function PayoutDesk({
  pendingAddress,
  withdraw,
}: {
  pendingAddress: string;
  withdraw: ScriptStep;
}) {
  const destination = fieldValue(withdraw, "destination");
  const pending = paired(pendingAddress, destination);
  const recipient = fieldValue(withdraw, "recipient").trim();

  return (
    <section className="ton-step" id="payout-form" aria-labelledby="step-6-title">
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">Step 6 · Payout</p>
          <h2 id="step-6-title">Query, ack, and proxy payout</h2>
        </div>
      </div>
      <p className="ton-section-copy">
        After <a href="#withdraw-form">step 5</a>, the pending withdraw asks the
        minter for the current price, then proxy_ton pays the recipient. These
        messages stay between the contracts. Opcode 0x1001 goes to the minter,
        opcode 0x1002 comes back, and opcode 0x4004 goes to the proxy.
      </p>

      <label className="ton-field">
        <span>Pending withdraw</span>
        <input readOnly value={pending} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">
        The contract from step 4 and the destination on step 5.
        {pendingAddress.trim() !== destination.trim() ? " Those two differ." : ""}
      </p>

      <label className="ton-field">
        <span>Recipient</span>
        <input readOnly value={recipient} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">From step 5. The proxy sends the TON to this address.</p>

      <label className="ton-field">
        <span>Minter</span>
        <input readOnly value={utonMinter} spellCheck={false} autoComplete="off" />
      </label>
      <p className="ton-hint">
        query_data is sent here. Price and supply are not read from the chain.
      </p>

      <p className="ton-section-copy">
        Finished is a 1-bit flag. query_ack sets it to 1 before the proxy
        notification. If that notification bounces, on_bounce on the withdraw
        contract clears it. Not read from the chain.
      </p>

      <ol className="ton-flow" aria-label="After the owner withdraw">
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
      <p className="ton-hint">
        The pending withdraw asks the minter for the price, keeps the lower TON
        amount, and proxy_ton pays the recipient. A static list. Not a chain read.
      </p>
      <p className="ton-hint">
        This leg is contract-to-contract after step 5. Payout is not a user message.
      </p>
    </section>
  );
}

function fieldValue(step: ScriptStep, id: string): string {
  if (id === "destination") return step.destination.trim();
  if (step.body.kind !== "fields") return "";
  return step.body.fields.find((field) => field.id === id)?.value ?? "";
}

function paired(leftRaw: string, rightRaw: string): string {
  const left = leftRaw.trim();
  const right = rightRaw.trim();
  if (left === right) return left;
  return `Step 4 ${left || "—"} · Step 5 ${right || "—"}`;
}
