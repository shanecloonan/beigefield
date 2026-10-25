import { utonLinks, utonMinter, utonSource } from "@/lib/uton";
import { UTON_BURN_FORWARD_START, UTON_OP } from "@/lib/uton-templates";

const burnNotes = [
  {
    title: "What this message does",
    text: "It burns uTON in the jetton wallet with proxy id 3. The wallet checks the owner and the balance, copies withdraw_cnt, increments that counter, reduces the balance, and notifies the minter. The custom payload is a dictionary. Key 0 holds the proxy id, the forward value, and an empty forward cell.",
  },
  {
    title: "Where to send it",
    text: "The destination is the holder's uTON jetton wallet. Paste that address. This page does not derive it.",
  },
  {
    title: "Why proxy id 3",
    text: "Proxy id 3 is not on the minter whitelist. The wallet does not check the whitelist. The minter does, on the notification.",
  },
] as const;

const notifyNotes = [
  {
    title: "Balance already reduced",
    text: "The jetton wallet reduces its balance, and increments withdraw_cnt, before it sends this notification.",
  },
  {
    title: "Layout",
    text: "The owner address is stored before the withdraw id and the uTON amount. The proxy id follows the amount.",
  },
  {
    title: "The bounce",
    text: "The message is bounceable. The minter throws when proxy id 3 is missing from the whitelist, before it changes supply. The bounce returns to on_bounce on the wallet.",
  },
] as const;

const bounceNotes = [
  {
    title: "Which messages it accepts",
    text: "on_bounce accepts a bounced internal transfer or a bounced burn notification. The minter and proxy_ton return immediately on a bounce and do not run this handler.",
  },
  {
    title: "Where it reads coins",
    text: "After the opcode and the query id it calls load_coins(). An internal transfer stores the uTON amount there. This burn notification stores the owner address there.",
  },
  {
    title: "What it writes",
    text: "It adds that coin read to balance and saves. withdraw_cnt stays at the value burn_tokens left. The handler does not parse a number on this page.",
  },
] as const;

const redeemNotes = [
  {
    title: "A whitelisted proxy id",
    text: "The redeem burn is the same opcode, sent to the same jetton wallet, with a proxy id the minter whitelist contains. The field starts blank. This page does not read the whitelist.",
  },
  {
    title: "The wallet again",
    text: "burn_tokens subtracts the balance and takes another withdraw id, then sends a bounceable notification to the minter.",
  },
  {
    title: "If the minter accepts it",
    text: "proxy_burn resolves the proxy id before it changes supply. The caller must be the jetton wallet of the owner. The proxy then records the priced TON and deploys a pending withdraw.",
  },
] as const;

export function UtonNotes() {
  return (
    <>
      <nav className="ton-contents" aria-label="On this page">
        <a href="#burn">Step 1</a>
        <a href="#burn-notify">Step 2</a>
        <a href="#bounce">Step 3</a>
        <a href="#redeem">Step 4</a>
        <a href="#redeem-notify">Step 5</a>
        <a href="#user-withdraw">Step 6</a>
      </nav>

      <section className="ton-section" id="burn" aria-labelledby="ton-burn-title">
        <h2 id="ton-burn-title">Step 1 · Burn with proxy id 3</h2>
        <p className="ton-section-copy">
          Opcode {UTON_OP.burn}. The body is a 64-bit query id, the uTON amount,
          and the response address. Proxy id is a 32-bit field in the custom
          payload and starts at 3. Forward value starts at {UTON_BURN_FORWARD_START}{" "}
          nanotons. The empty forward cell is not editable here.
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
        <h2 id="ton-notify-title">Step 2 · Notification that bounces</h2>
        <p className="ton-section-copy">
          Opcode {UTON_OP.burnNotification}. The destination is the minter{" "}
          {utonMinter}. The body stores a 64-bit query id, the owner address,
          a 64-bit withdraw id, the uTON amount, a 32-bit proxy id, the
          response address, and the forward value. Proxy id starts at 3.
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
          <a href="#notify-form">Open the notification form</a>
        </div>
      </section>

      <section className="ton-section" id="bounce" aria-labelledby="ton-bounce-title">
        <h2 id="ton-bounce-title">Step 3 · on_bounce</h2>
        <p className="ton-section-copy">
          The wallet&apos;s on_bounce runs for the bounced step 2. It skips the
          0xFFFFFFFF prefix, checks the opcode, loads the query id, and loads
          coins. Those coins are added to balance.
        </p>
        <ol className="ton-flow">
          {bounceNotes.map((note, index) => (
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
          <a href="#bounce-form">Open the on_bounce desk</a>
        </div>
      </section>

      <section className="ton-section" id="redeem" aria-labelledby="ton-redeem-title">
        <h2 id="ton-redeem-title">Step 4 · Redeem burn</h2>
        <p className="ton-section-copy">
          Opcode {UTON_OP.burn} again. Proxy id is left blank for an id the
          whitelist contains. The rest of the body matches step 1.
        </p>
        <ol className="ton-flow">
          {redeemNotes.map((note, index) => (
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
          <a href={utonLinks.proxyTon} target="_blank" rel="noreferrer">
            proxy_ton at {utonSource.short}
          </a>
          <a href="#redeem-form">Open the redeem burn</a>
        </div>
      </section>

      <section className="ton-section" id="redeem-notify" aria-labelledby="ton-redeem-notify-title">
        <h2 id="ton-redeem-notify-title">Step 5 · Redeem notification</h2>
        <p className="ton-section-copy">
          Opcode {UTON_OP.burnNotification} again, to the minter {utonMinter}.
          The proxy id matches the redeem burn. When that id is on the
          whitelist, the minter prices the burn, reduces supply, and sends
          opcode 0x1004 to the proxy. proxy_ton deploys a pending withdraw
          with opcode 0x4501.
        </p>
        <div className="ton-links">
          <a href={utonLinks.minter} target="_blank" rel="noreferrer">
            Minter at {utonSource.short}
          </a>
          <a href={utonLinks.withdraw} target="_blank" rel="noreferrer">
            Withdraw at {utonSource.short}
          </a>
          <a href="#redeem-notify-form">Open the redeem notification</a>
        </div>
      </section>

      <section className="ton-section" id="user-withdraw" aria-labelledby="ton-user-withdraw-title">
        <h2 id="ton-user-withdraw-title">Step 6 · Withdraw, then payout</h2>
        <p className="ton-section-copy">
          Opcode {UTON_OP.withdraw}. The owner sends this to the pending
          withdraw contract after withdraw_pending_time has elapsed. The body
          is a 64-bit query id, the recipient, and the response address. The
          attached TON is gas. The contract then queries the minter. That
          exchange is <a href="#payout-form">the payout desk</a>. Send stays
          locked there too.
        </p>
        <div className="ton-links">
          <a href={utonLinks.withdraw} target="_blank" rel="noreferrer">
            Withdraw at {utonSource.short}
          </a>
          <a href={utonLinks.proxyTon} target="_blank" rel="noreferrer">
            proxy_ton at {utonSource.short}
          </a>
          <a href="#withdraw-form">Open the withdraw form</a>
        </div>
      </section>
    </>
  );
}
