"use client";

import { SourceList } from "@/components/tons/source-block";
import { pathSource } from "@/lib/uton-path";

export type BounceNotice =
  | {
      tone: "good";
      text: string;
      href: string;
      hrefLabel: string;
    }
  | {
      tone: "bad";
      text: string;
    };

export function BounceDesk({
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
    <section className="ton-step" id="bounce-form" aria-labelledby="step-3-title">
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">Step 3 · on_bounce</p>
          <h2 id="step-3-title">on_bounce</h2>
        </div>
      </div>
      <SourceList sources={[pathSource.walletOnBounce]} />
      <p className="ton-hint">
        Send broadcasts the step 2 burn notification on mainnet. If the minter
        rejects proxy id 3, that message bounces back to the wallet. A sent
        message is final.
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
