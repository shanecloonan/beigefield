"use client";

import { SourceList } from "@/components/tons/source-block";
import type { BounceNotice } from "@/components/tons/bounce-desk";
import type { PathSource } from "@/lib/uton-path";

export function AutomationGap({
  id,
  titleId,
  kicker,
  title,
  sources,
  hint,
  sending,
  sendLabel,
  disabled,
  notice,
  onSend,
}: {
  id: string;
  titleId: string;
  kicker: string;
  title: string;
  sources: readonly PathSource[];
  hint: string;
  sending: boolean;
  sendLabel: string;
  disabled: boolean;
  notice: BounceNotice | null;
  onSend: () => void;
}) {
  return (
    <section className="ton-step" id={id} aria-labelledby={titleId}>
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">{kicker}</p>
          <h2 id={titleId}>{title}</h2>
        </div>
      </div>
      <SourceList sources={sources} />
      <p className="ton-hint">{hint}</p>
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
