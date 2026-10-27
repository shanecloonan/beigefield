import {
  KATANA_STRUCTURED_GENERIC_PROGRAM,
  KATANA_STRUCTURED_PROGRAM,
  solExplorerAccountUrl,
} from "@/lib/katana";

export function KatanaNotes() {
  return (
    <section className="ton-notes" aria-labelledby="katana-notes-title">
      <h2 id="katana-notes-title" className="ton-subhead">
        Status
      </h2>
      <p>
        Katana is the Solana covered-call and secured-put vault program that
        ran at katana.so. PsyFi acquired it in April 2023 and told users the
        vaults were paused. The two programs are still deployed:
      </p>
      <dl className="ton-ref">
        <div>
          <dt>structured</dt>
          <dd>
            <a href={solExplorerAccountUrl(KATANA_STRUCTURED_PROGRAM)} target="_blank" rel="noreferrer">
              {KATANA_STRUCTURED_PROGRAM}
            </a>
          </dd>
        </div>
        <div>
          <dt>structuredGeneric</dt>
          <dd>
            <a href={solExplorerAccountUrl(KATANA_STRUCTURED_GENERIC_PROGRAM)} target="_blank" rel="noreferrer">
              {KATANA_STRUCTURED_GENERIC_PROGRAM}
            </a>
          </dd>
        </div>
      </dl>
      <p>
        Most State accounts now report <code>isExpired</code>. Recent mainnet
        traffic is claim_shares, withdraw_expired, complete_withdraw, and
        close_user_account. Deposit is rejected on an expired vault. The
        post-acquisition migrate button funded a PsyFi vault; PsyFi shut its
        services on 1 May 2025, so migrate is not offered.
      </p>
    </section>
  );
}
