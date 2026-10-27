"use client";

export type PathNotice =
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
  notice: PathNotice | null;
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
        Run path signs one Katana instruction set with the desk wallet. Deposit
        is not sent: expired vaults reject it. Migrate is not sent: that path
        deposited into PsyFi, which shut down on 1 May 2025. Remaining user
        instructions are claim_shares, withdraw_expired, complete_withdraw,
        instant_withdraw, and close_user_account.
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
