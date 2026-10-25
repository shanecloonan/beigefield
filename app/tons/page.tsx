import type { Metadata } from "next";
import { TonComposer } from "@/components/tons/ton-composer";
import { UtonNotes } from "@/components/tons/uton-notes";
import { site, tonManifestUrl } from "@/lib/site";
import Link from "next/link";

const title = `Bounce, then redeem — ${site.name}`;
const description =
  "The uTON burn with proxy id 3, the bounced notification, the wallet on_bounce read, and a later redeem on a whitelisted proxy. Send stays locked.";

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
        <p className="ton-kicker">Proxy id 3, then a whitelisted id</p>
        <h1>Bounce, then redeem</h1>
        <p className="ton-lede">
          Step 1 burns uTON from the jetton wallet with proxy id 3. That id is
          not on the minter whitelist. The wallet still reduces its balance
          and takes the next withdraw id, then sends the burn notification.
          Step 2 is that notification. The minter throws before it changes
          supply, and the bounceable message returns. Step 3 is on_bounce on
          the wallet. It accepts the bounced burn notification, reads coins
          where the owner address was stored, and adds that read to the
          balance. withdraw_cnt stays where burn_tokens left it. Step 4 burns
          again with a proxy id the whitelist contains. Step 5 is the
          notification for that burn. Step 6 is the owner withdraw after the
          time lock, and the payout the contracts run after that. Send is
          locked on every step. Nothing on this page is broadcast.
        </p>
        <UtonNotes />
        <TonComposer manifestUrl={tonManifestUrl} />
      </main>
    </div>
  );
}
