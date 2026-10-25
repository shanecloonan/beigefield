"use client";

import type { BounceNotice } from "@/components/tons/bounce-desk";

export function PathRunBar({
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
  notice: BounceNotice | null;
  lookupNote: string | null;
  onRun: () => void;
}) {
  return (
    <section className="ton-step" id="path-run" aria-labelledby="path-run-title">
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">Whole path</p>
          <h2 id="path-run-title">One send</h2>
        </div>
      </div>
      <p className="ton-hint">
        Run path sends the burn, the burn notification, the redeem burn, and the
        redeem notification, in that order. The minter query follows when the
        withdraw fields are ready. The withdraw itself is included only after
        its contract address is filled. The wallet confirms each batch.
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
