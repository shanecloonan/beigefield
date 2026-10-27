import { KATANA_STRUCTURED_PROGRAM, solExplorerAccountUrl } from "@/lib/katana";

export function KatanaAuthorizedNotes() {
  return (
    <section className="ton-notes" aria-labelledby="katana-notes-title">
      <h2 id="katana-notes-title" className="ton-subhead">
        Withdraw pending deposit
      </h2>
      <p>
        This page returns a pending deposit that is still in the current vault
        round. It does not move locked vault capital or share balances.
      </p>
      <p>
        The connected wallet signs and pays the network fee. userAuthority
        and destination can be set separately. Tokens go to destination.
        That account is created in the same transaction if it is missing
        and it is this userAuthority&apos;s associated token account.
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
          <dd>instantWithdraw</dd>
        </div>
      </dl>
    </section>
  );
}
