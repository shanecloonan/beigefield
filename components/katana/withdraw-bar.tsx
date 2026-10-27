"use client";

import type { PathNotice } from "@/components/sol/path-run-bar";

export function WithdrawBar({
  sending,
  label,
  disabled,
  notice,
  lookupNote,
  onRun,
}: {
  sending: boolean;
  label: string;
  disabled: boolean;
  notice: PathNotice | null;
  lookupNote: string | null;
  onRun: () => void;
}) {
  return (
    <section className="ton-step" id="withdraw" aria-labelledby="withdraw-title">
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">instantWithdraw</p>
          <h2 id="withdraw-title">Withdraw pending deposit</h2>
        </div>
      </div>
      <p className="ton-hint">
        Builds instantWithdraw (16-byte data, eight IDL accounts). The
        connected wallet is the fee payer; userAuthority is not an instruction
        signer. User authority and destination are chosen separately. Only a
        same-round pending deposit can be withdrawn here. Locked capital,
        prior-round deposits, and vault shares need other instructions.
      </p>
      <button
        type="button"
        className="ton-button ton-button-lead"
        onClick={onRun}
        disabled={disabled}
        aria-busy={sending}
      >
        {label}
      </button>
      <div aria-live="polite">
        {sending ? (
          <p className="ton-status" role="status">
            {label}
          </p>
        ) : null}
        {lookupNote ? (
          <p className="ton-hint" role="status">
            {lookupNote}
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
