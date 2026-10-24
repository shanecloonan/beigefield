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

export function UtonNotes() {
  return (
    <>
      <nav className="ton-contents" aria-label="On this page">
        <a href="#stake">Step 1</a>
        <a href="#burn">Step 2</a>
        <a href="#burn-notify">Step 3</a>
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
    </>
  );
}
