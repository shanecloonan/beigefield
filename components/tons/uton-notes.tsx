import { utonLinks, utonSource } from "@/lib/uton";
import { UTON_OP } from "@/lib/uton-templates";

const notes = [
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

export function UtonNotes() {
  return (
    <>
      <nav className="ton-contents" aria-label="On this page">
        <a href="#stake">This step</a>
        <a href="#message">Stake</a>
      </nav>

      <section className="ton-section" id="stake" aria-labelledby="ton-stake-title">
        <h2 id="ton-stake-title">Step 1</h2>
        <p className="ton-section-copy">
          Opcode {UTON_OP.stake}. proxy_ton reads that value. The TL-B sketch
          writes stake as 0x1000. The body after the opcode is a 64-bit query
          id, the user address, and the response address.
        </p>
        <ol className="ton-flow">
          {notes.map((note, index) => (
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
          <a href={utonLinks.interface} target="_blank" rel="noreferrer">
            Message interface
          </a>
        </div>
      </section>
    </>
  );
}
