import { SourceList } from "@/components/tons/source-block";
import type { PathSource } from "@/lib/uton-path";

export function AutomationGap({
  id,
  titleId,
  kicker,
  title,
  sources,
}: {
  id: string;
  titleId: string;
  kicker: string;
  title: string;
  sources: readonly PathSource[];
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
      <button type="button" className="ton-button" disabled aria-disabled="true">
        Send
      </button>
    </section>
  );
}
