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
        Run path reads a completed-unbonding id from the LCD, then broadcasts one
        MsgExecuteContract. The contract is the Valdora staker. The msg is
        withdraw_unbonded_by_id. The message funds are empty. The fee is azig from
        the desk account.
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
