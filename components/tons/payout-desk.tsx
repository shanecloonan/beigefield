import { PathSendButton } from "@/components/tons/path-send-button";
import { SourceList } from "@/components/tons/source-block";
import { pathSource } from "@/lib/uton-path";

export function PayoutDesk() {
  return (
    <section className="ton-step" id="payout-form" aria-labelledby="payout-title">
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">After step 6</p>
          <h2 id="payout-title">query_ack</h2>
        </div>
      </div>
      <SourceList sources={[pathSource.queryAck, pathSource.proxyWithdraw]} />
      <PathSendButton detail="Nothing was sent. query_ack runs between the pending withdraw and the minter." />
    </section>
  );
}
