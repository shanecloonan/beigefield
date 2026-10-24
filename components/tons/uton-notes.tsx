import { utonLinks, utonMinter, utonSource } from "@/lib/uton";
import { UTON_BURN_FORWARD_START, UTON_OP } from "@/lib/uton-templates";

const stakeNotes = [
  {
    title: "What this message does",
    text: "It deposits native TON with proxy_ton. The body names the address that should receive the minted uTON, and the address that should receive excess gas. The proxy then notifies the minter.",
  },
  {
    title: "Where to send it",
    text: "The destination is proxy_ton, the native-TON proxy on the minter whitelist. Paste that address. This page does not read the whitelist.",
  },
  {
    title: "Bounceable",
    text: "The destination is bounceable by default, so the TON can return if proxy_ton does not accept the stake.",
  },
] as const;

const burnNotes = [
  {
    title: "What this message does",
    text: "It burns uTON in your jetton wallet. The wallet checks the balance, then notifies the minter. The custom payload is a dictionary. Key 0 holds the proxy id, the forward value, and an empty forward cell.",
  },
  {
    title: "Where to send it",
    text: "The destination is your uTON jetton wallet. Paste that address. This page does not derive it.",
  },
  {
    title: "Bounceable",
    text: "The destination is bounceable by default, so the attached TON can return if that wallet does not accept the burn.",
  },
] as const;

const notifyNotes = [
  {
    title: "Balance already reduced",
    text: "The jetton wallet reduces its balance before it sends this notification.",
  },
  {
    title: "Bounceable",
    text: "The message is bounceable. The destination is the minter.",
  },
  {
    title: "If the minter rejects it",
    text: "If the minter rejects the notification, for example an invalid proxy id, the bounce returns to on_bounce on the wallet.",
  },
] as const;

const proxyNotes = [
  {
    title: "Whitelist, then supply",
    text: "proxy_burn resolves the proxy id on the whitelist before it changes total supply. The caller must be the jetton wallet of the owner on the notification.",
  },
  {
    title: "Pending withdraw",
    text: "The proxy deploys one withdraw contract for the owner and withdraw id. State init stores finished as 0. The address depends on the withdraw code, so this page does not derive it.",
  },
  {
    title: "Time lock",
    text: "withdraw_timestamp is the burn time plus withdraw_pending_time on the proxy. The published unstake wait is 3 days. The duration is not a constant in the source.",
  },
] as const;

export function UtonNotes() {
  return (
    <>
      <nav className="ton-contents" aria-label="On this page">
        <a href="#stake">Step 1</a>
        <a href="#burn">Step 2</a>
        <a href="#burn-notify">Step 3</a>
        <a href="#proxy-burn">Step 4</a>
        <a href="#user-withdraw">Step 5</a>
        <a href="#payout">Step 6</a>
      </nav>

      <section className="ton-section" id="stake" aria-labelledby="ton-stake-title">
        <h2 id="ton-stake-title">Step 1 · Stake native TON</h2>
        <p className="ton-section-copy">
          Opcode {UTON_OP.stake}. proxy_ton reads that value. The TL-B sketch
          writes stake as 0x1000. The body after the opcode is a 64-bit query
          id, the user address, and the response address.
        </p>
        <ol className="ton-flow">
          {stakeNotes.map((note, index) => (
            <li key={note.title}>
              <span className="ton-flow-index">{index + 1}</span>
              <div>
                <h3>{note.title}</h3>
                <p>{note.text}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="ton-links">
          <a href={utonLinks.proxyTon} target="_blank" rel="noreferrer">
            proxy_ton at {utonSource.short}
          </a>
          <a href="#stake-form">Open the stake form</a>
        </div>
      </section>

      <section className="ton-section" id="burn" aria-labelledby="ton-burn-title">
        <h2 id="ton-burn-title">Step 2 · uTON burn</h2>
        <p className="ton-section-copy">
          Opcode {UTON_OP.burn}. The body is a 64-bit query id, the uTON amount,
          and the response address. Proxy id is a 32-bit field in the custom
          payload, with the forward value. Forward value starts at{" "}
          {UTON_BURN_FORWARD_START} nanotons. The empty forward cell is not
          editable here.
        </p>
        <ol className="ton-flow">
          {burnNotes.map((note, index) => (
            <li key={note.title}>
              <span className="ton-flow-index">{index + 1}</span>
              <div>
                <h3>{note.title}</h3>
                <p>{note.text}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="ton-links">
          <a href={utonLinks.wallet} target="_blank" rel="noreferrer">
            Jetton wallet at {utonSource.short}
          </a>
          <a href="#burn-form">Open the burn form</a>
        </div>
      </section>

      <section className="ton-section" id="burn-notify" aria-labelledby="ton-notify-title">
        <h2 id="ton-notify-title">Step 3 · Burn notification</h2>
        <p className="ton-section-copy">
          Opcode {UTON_OP.burnNotification}. The destination is the minter{" "}
          {utonMinter}. The body stores a 64-bit query id, the owner address,
          a 64-bit withdraw id, the uTON amount, a 32-bit proxy id, the
          response address, and the forward value. The owner is stored before
          the amount. An empty forward cell is attached and is not editable
          here.
        </p>
        <ol className="ton-flow">
          {notifyNotes.map((note, index) => (
            <li key={note.title}>
              <span className="ton-flow-index">{index + 1}</span>
              <div>
                <h3>{note.title}</h3>
                <p>{note.text}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="ton-links">
          <a href={utonLinks.minter} target="_blank" rel="noreferrer">
            Minter at {utonSource.short}
          </a>
          <a href={utonLinks.wallet} target="_blank" rel="noreferrer">
            Jetton wallet at {utonSource.short}
          </a>
          <a href="#notify-form">Open the burn notification form</a>
        </div>
      </section>

      <section className="ton-section" id="proxy-burn" aria-labelledby="ton-proxy-burn-title">
        <h2 id="ton-proxy-burn-title">Step 4 · Proxy burn and pending withdraw</h2>
        <p className="ton-section-copy">
          The minter handles opcode {UTON_OP.burnNotification} in proxy_burn.
          It checks the proxy id, then reduces supply and sends opcode 0x1004
          to that proxy. proxy_ton records the priced TON as debt and deploys
          a pending withdraw with opcode 0x4501. A missing proxy id throws
          before the supply change. That return is the bounce on step 3.
        </p>
        <ol className="ton-flow">
          {proxyNotes.map((note, index) => (
            <li key={note.title}>
              <span className="ton-flow-index">{index + 1}</span>
              <div>
                <h3>{note.title}</h3>
                <p>{note.text}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="ton-links">
          <a href={utonLinks.minter} target="_blank" rel="noreferrer">
            Minter at {utonSource.short}
          </a>
          <a href={utonLinks.proxyTon} target="_blank" rel="noreferrer">
            proxy_ton at {utonSource.short}
          </a>
          <a href={utonLinks.withdraw} target="_blank" rel="noreferrer">
            Withdraw at {utonSource.short}
          </a>
          <a href="#proxy-burn-form">Open the proxy burn desk</a>
        </div>
      </section>

      <section className="ton-section" id="user-withdraw" aria-labelledby="ton-user-withdraw-title">
        <h2 id="ton-user-withdraw-title">Step 5 · Withdraw</h2>
        <p className="ton-section-copy">
          Opcode {UTON_OP.withdraw}. The owner sends this to the pending
          withdraw contract after withdraw_pending_time has elapsed. The body
          is a 64-bit query id, the recipient, and the response address. The
          attached TON is gas. The contract then queries the minter. That
          exchange is <a href="#payout-form">step 6</a> and is not sent from
          this page.
        </p>
        <div className="ton-links">
          <a href={utonLinks.withdraw} target="_blank" rel="noreferrer">
            Withdraw at {utonSource.short}
          </a>
          <a href="#withdraw-form">Open the withdraw form</a>
        </div>
      </section>

      <section className="ton-section" id="payout" aria-labelledby="ton-payout-title">
        <h2 id="ton-payout-title">Step 6 · Query, ack, and proxy payout</h2>
        <p className="ton-section-copy">
          The pending withdraw from <a href="#withdraw-form">step 5</a> sends
          opcode 0x1001 to the minter. The minter answers with opcode 0x1002.
          A later price can only lower the TON stored on the withdraw. The
          contract then sends opcode 0x4004 to proxy_ton, which pays the
          recipient. Price and supply are not read here.
        </p>
        <div className="ton-links">
          <a href={utonLinks.minter} target="_blank" rel="noreferrer">
            Minter at {utonSource.short}
          </a>
          <a href={utonLinks.withdraw} target="_blank" rel="noreferrer">
            Withdraw at {utonSource.short}
          </a>
          <a href={utonLinks.proxyTon} target="_blank" rel="noreferrer">
            proxy_ton at {utonSource.short}
          </a>
          <a href="#payout-form">Open the payout desk</a>
        </div>
      </section>
    </>
  );
}
