import type { Metadata } from "next";
import { TonComposer } from "@/components/tons/ton-composer";
import { UtonNotes } from "@/components/tons/uton-notes";
import { site, tonManifestUrl } from "@/lib/site";
import Link from "next/link";

const title = `Stake, burn, notify — ${site.name}`;
const description =
  "Three uTON messages on mainnet: a native TON stake to proxy_ton (opcode 0x1003), a burn from your uTON jetton wallet (opcode 0x595f07bc), then the burn notification that wallet sends to the minter (opcode 0x7bdd97de).";

export const metadata: Metadata = {
  title,
  description,
  alternates: {
    canonical: "/tons",
  },
  openGraph: {
    title,
    description,
    url: `${site.url}/tons`,
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
  },
};

export default function TonPage() {
  return (
    <div className="page">
      <div className="frame" aria-hidden="true">
        <span className="corner corner-tl" />
        <span className="corner corner-tr" />
        <span className="corner corner-bl" />
        <span className="corner corner-br" />
      </div>
      <main className="ton-main">
        <Link className="ton-mark" href="/">
          Beigefield
        </Link>
        <p className="ton-kicker">Steps 1–3 · mainnet</p>
        <h1>Stake, burn, notify</h1>
        <p className="ton-lede">
          Step 1 deposits native TON with proxy_ton. Step 2 burns uTON from
          your jetton wallet. Step 3 is the burn notification that wallet
          sends to the minter. Each message is filled and sent on its own.
        </p>
        <UtonNotes />
        <TonComposer manifestUrl={tonManifestUrl} />
      </main>
    </div>
  );
}
