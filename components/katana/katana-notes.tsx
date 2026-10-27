import { KATANA_STRUCTURED_PROGRAM, solExplorerAccountUrl } from "@/lib/katana";

export function KatanaAuthorizedNotes() {
  return (
    <section className="ton-notes" aria-labelledby="katana-notes-title">
      <h2 id="katana-notes-title" className="ton-subhead">
        Withdraw pending deposit
      </h2>
      <p>
        This page returns a pending deposit that is still in the current vault
        round. It does not move locked vault capital, prior-round deposits, or
        vault share balances — those stay on claim_shares, initiate_withdraw,
        and complete_withdraw.
      </p>
      <p>
        The connected wallet is the fee payer. Tokens are sent only to this
        wallet&apos;s associated token account for the vault&apos;s underlying
        mint. That account is created in the same transaction if it is missing.
        A third-party token account cannot be set as the destination.
      </p>
      <dl className="ton-ref">
        <div>
          <dt>Program</dt>
          <dd>
            <a href={solExplorerAccountUrl(KATANA_STRUCTURED_PROGRAM)} target="_blank" rel="noreferrer">
              {KATANA_STRUCTURED_PROGRAM}
            </a>
          </dd>
        </div>
        <div>
          <dt>Instruction</dt>
          <dd>instantWithdraw · ab3191b0306570a2</dd>
        </div>
        <div>
          <dt>mSOL State</dt>
          <dd>
            <a href={solExplorerAccountUrl("DkguYGWhRE8qJ9voWNYZ8dJkGYr8ACUR8KXqDAyHpGx2")} target="_blank" rel="noreferrer">
              DkguYGWhRE8qJ9voWNYZ8dJkGYr8ACUR8KXqDAyHpGx2
            </a>
          </dd>
        </div>
        <div>
          <dt>stSOL State</dt>
          <dd>
            <a href={solExplorerAccountUrl("CPFuWtS7qNQt3RPnSt5opKph9JbqdW3LjxF1HEw3v1tP")} target="_blank" rel="noreferrer">
              CPFuWtS7qNQt3RPnSt5opKph9JbqdW3LjxF1HEw3v1tP
            </a>
          </dd>
        </div>
      </dl>
    </section>
  );
}
