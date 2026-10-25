import { PathSendButton } from "@/components/tons/path-send-button";
import { SourceList } from "@/components/tons/source-block";
import { pathSource } from "@/lib/uton-path";

export function BounceDesk() {
  return (
    <section className="ton-step" id="bounce-form" aria-labelledby="step-3-title">
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">Step 3 · on_bounce</p>
          <h2 id="step-3-title">on_bounce</h2>
        </div>
      </div>
      <SourceList sources={[pathSource.walletOnBounce]} />
      <PathSendButton detail="Nothing was sent. on_bounce runs on the jetton wallet when the notification returns." />
    </section>
  );
}
