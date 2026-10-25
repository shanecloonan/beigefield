"use client";

import { SourceList } from "@/components/tons/source-block";
import type { BounceNotice } from "@/components/tons/bounce-desk";
import { pathSource } from "@/lib/uton-path";
import { UTON_OP } from "@/lib/uton-templates";

export function PayoutDesk({
  sending,
  sendLabel,
  disabled,
  notice,
  onSend,
}: {
  sending: boolean;
  sendLabel: string;
  disabled: boolean;
  notice: BounceNotice | null;
  onSend: () => void;
}) {
  return (
    <section className="ton-step" id="payout-form" aria-labelledby="payout-title">
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">After step 6</p>
          <h2 id="payout-title">query_ack</h2>
        </div>
      </div>
      <SourceList sources={[pathSource.queryAck, pathSource.proxyWithdraw]} />
      <p className="ton-hint">
        Send broadcasts opcode {UTON_OP.query} to the minter, the query the{" "}
        <a href="#withdraw-form">withdraw</a> builds from its query id, recipient,
        and response address. The minter answers this sender with query_ack,
        opcode {UTON_OP.queryAck}. Attach more than 0.01 TON on the withdraw. A
        sent message is final.
      </p>
      <button
        type="button"
        className="ton-button"
        onClick={onSend}
        disabled={disabled}
        aria-busy={sending}
      >
        {sendLabel}
      </button>
      <div aria-live="polite">
        {sending ? (
          <p className="ton-status" role="status">
            {sendLabel}
          </p>
        ) : null}
        {notice ? (
          <p className={notice.tone === "good" ? "ton-good" : "ton-error"} role="status">
            {notice.text}{" "}
            {notice.tone === "good" ? (
              <a href={notice.href} target="_blank" rel="noreferrer">
                {notice.hrefLabel}
              </a>
            ) : null}
          </p>
        ) : null}
      </div>
    </section>
  );
}
