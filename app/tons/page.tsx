import type { Metadata } from "next";
import { TonComposer } from "@/components/tons/ton-composer";
import { UtonNotes } from "@/components/tons/uton-notes";
import { site, tonManifestUrl } from "@/lib/site";
import Link from "next/link";

const title = `Stake through payout — ${site.name}`;
const description =
  "Six uTON steps on mainnet, from a native TON stake through burn, the minter notification, the pending withdraw, the owner withdraw, and the contract payout.";

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
        <p className="ton-kicker">Steps 1–6 · mainnet</p>
        <h1>Stake through payout</h1>
        <p className="ton-lede">
          Step 1 deposits native TON with proxy_ton. Step 2 burns uTON from
          your jetton wallet. Step 3 is the burn notification that wallet
          sends to the minter. Step 4 is the pending withdraw the minter and
          proxy create after that notification is accepted. Step 5 is the
          owner withdraw to that contract, after the time lock. Step 6 is the
          query, the ack, and the proxy payout. Steps 1–3 and 5 are sent on
          their own. Steps 4 and 6 are not user messages.
        </p>
        <UtonNotes />
        <TonComposer manifestUrl={tonManifestUrl} />
      </main>
    </div>
  );
}
