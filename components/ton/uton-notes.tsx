import { CopyButton } from "@/components/ton/copy-button";
import { utonLinks, utonMinter, utonSource } from "@/lib/uton";

const contracts = [
  {
    name: "Minter",
    href: utonLinks.minter,
    text: "Jetton master. It holds supply, the TON price of uTON, and the proxy whitelist.",
  },
  {
    name: "Wallet",
    href: utonLinks.wallet,
    text: "One jetton wallet per holder. A burn starts here, in burn_tokens.",
  },
  {
    name: "proxy_ton",
    href: utonLinks.proxyTon,
    text: "Native TON stake, and the burn that opens a withdrawal. The source marks this proxy type 0. Its address is the one stored on the minter whitelist.",
  },
  {
    name: "Withdraw",
    href: utonLinks.withdraw,
    text: "Created per withdrawal. It keeps the time lock, reads a price from the minter, then asks the proxy to pay.",
  },
] as const;

const routes = [
  ["Stake native TON", "proxy_ton"],
  ["Stake an LST", "That proxy's LST jetton wallet"],
  ["Burn uTON", "The holder's uTON wallet"],
  ["Withdraw", "The withdraw contract for that withdraw id"],
] as const;

const stake = [
  {
    title: "Deposit",
    text: "The user sends native TON to proxy_ton with a stake message: who should receive the uTON, and where excess gas returns.",
  },
  {
    title: "Notify",
    text: "The proxy forwards the staked TON to its configured receiver and tells the minter the proxy type, proxy id, and TON amount.",
  },
  {
    title: "Mint",
    text: "The minter accepts that caller only when the proxy id is on the whitelist and the type matches. It prices the deposit, increases supply, and mints uTON into the user's jetton wallet.",
  },
] as const;

const redeem = [
  {
    title: "burn_tokens",
    text: "The owner sends a burn to their own uTON wallet. The wallet checks the owner and the balance, takes the next withdraw id, reduces the jetton balance, and notifies the minter.",
  },
  {
    title: "on_bounce",
    text: "If that notification bounces, the wallet's on_bounce runs. It accepts a bounced internal transfer or burn notification, credits the balance from the coin field after the query id, and leaves withdraw_cnt unchanged.",
  },
  {
    title: "proxy_burn",
    text: "The minter accepts the notification from that user's jetton wallet. It resolves the proxy id on the whitelist, prices the burn, reduces supply, and forwards the burn to the proxy.",
  },
  {
    title: "Proxy burn",
    text: "proxy_ton records the TON amount as debt and creates a withdraw contract for that user and withdraw id. The contract stores the burn price and a withdraw time: the burn time plus the proxy's pending time.",
  },
  {
    title: "Time lock",
    text: "The owner can call withdraw on that contract once the withdraw time has passed, and while the withdrawal is not already finished.",
  },
  {
    title: "query_data / query_ack",
    text: "Withdraw asks the minter for the current price and supply. The minter answers the caller with query_ack. A lower price can reduce the TON to be paid. The contract then marks the withdrawal finished.",
  },
  {
    title: "Proxy withdraw",
    text: "The contract notifies proxy_ton. The proxy checks that the sender is the withdraw contract for that id, reduces the debt, and sends native TON to the recipient.",
  },
] as const;

export function UtonNotes() {
  return (
    <>
      <nav className="ton-contents" aria-label="On this page">
        <a href="#reference">Reference</a>
        <a href="#stake">Stake</a>
        <a href="#redeem">Redeem</a>
        <a href="#notes">Notes</a>
        <a href="#message">Message</a>
      </nav>

      <section className="ton-section" id="reference" aria-labelledby="ton-reference-title">
        <h2 id="ton-reference-title">Reference</h2>
        <p className="ton-section-copy">
          The minter below is the mainnet jetton master. Proxy addresses live on
          its whitelist. This page does not query the chain, so price, supply,
          and those proxies stay on the contract.
        </p>

        <dl className="ton-ref">
          <div>
            <dt>Minter</dt>
            <dd>
              <p className="ton-mono">{utonMinter}</p>
              <div className="ton-links">
                <CopyButton value={utonMinter} label="Copy address" />
                <a href={utonLinks.tonviewer} target="_blank" rel="noreferrer">
                  Tonviewer
                </a>
              </div>
            </dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>
              <p className="ton-mono">
                {utonSource.repo} @ {utonSource.short}
              </p>
              <div className="ton-links">
                <a href={utonLinks.tree} target="_blank" rel="noreferrer">
                  Contracts at {utonSource.short}
                </a>
                <a href={utonLinks.docs} target="_blank" rel="noreferrer">
                  Architecture note
                </a>
                <a href={utonLinks.interface} target="_blank" rel="noreferrer">
                  Message interface
                </a>
              </div>
            </dd>
          </div>
        </dl>

        <div className="ton-roles">
          {contracts.map((contract) => (
            <article className="ton-role" key={contract.name}>
              <h3>
                <a href={contract.href} target="_blank" rel="noreferrer">
                  {contract.name}
                </a>
              </h3>
              <p>{contract.text}</p>
            </article>
          ))}
        </div>

        <h3 className="ton-subhead">Where a message goes</h3>
        <dl className="ton-where">
          {routes.map(([action, target]) => (
            <div key={action}>
              <dt>{action}</dt>
              <dd>{target}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="ton-section" id="stake" aria-labelledby="ton-stake-title">
        <h2 id="ton-stake-title">Stake</h2>
        <p className="ton-section-copy">
          Native TON enters through proxy_ton. An LST deposit is a jetton
          transfer into the LST wallet of that proxy, which then stakes through
          the same minter. Either entry withdraws as native TON.
        </p>
        <ol className="ton-flow">
          {stake.map((step, index) => (
            <li key={step.title}>
              <span className="ton-flow-index">{index + 1}</span>
              <div>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="ton-section" id="redeem" aria-labelledby="ton-redeem-title">
        <h2 id="ton-redeem-title">Redeem</h2>
        <p className="ton-section-copy">
          A burn from the uTON wallet becomes a priced burn on a whitelisted
          proxy, then a withdraw contract that waits out the pending time on
          that proxy before native TON is sent.
        </p>
        <ol className="ton-flow">
          {redeem.map((step, index) => (
            <li key={step.title}>
              <span className="ton-flow-index">{index + 1}</span>
              <div>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="ton-section" id="notes" aria-labelledby="ton-notes-title">
        <h2 id="ton-notes-title">Notes from the source</h2>
        <div className="ton-notes">
          <p>
            The minter and proxy_ton return immediately when a message has
            bounced. The wallet and the withdraw contract each handle bounce on
            their own.
          </p>
          <p>
            On the withdraw contract, a bounced withdraw notification clears
            the finished flag.
          </p>
          <p>
            query_ack can lower the stored TON amount when the newer price pays
            less. It does not raise that amount.
          </p>
        </div>
      </section>
    </>
  );
}
