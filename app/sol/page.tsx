import type { Metadata } from "next";
import { KatanaNotes } from "@/components/sol/katana-notes";
import { SolComposer } from "@/components/sol/sol-composer";
import { site } from "@/lib/site";
import { SOL_FUNDED_WALLET_ADDRESS } from "@/lib/sol-funded-wallet-public";
import Link from "next/link";

const title = `Katana — ${site.name}`;
const description =
  "Katana structured vaults on Solana mainnet. The vaults are expired after the PsyFi acquisition. The desk wallet signs remaining claim, withdraw, and close instructions.";

export const metadata: Metadata = {
  title,
  description,
  alternates: {
    canonical: "/sol",
  },
  openGraph: {
    title,
    description,
    url: `${site.url}/sol`,
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
  },
};

export default function SolPage() {
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
        <p className="ton-kicker">Katana · Solana mainnet</p>
        <h1>Katana</h1>
        <p className="ton-lede">
          Covered-call and secured-put vaults on the Katana programs. Deposits
          stopped after the vaults expired. This desk only claims shares,
          withdraws remaining inventory, or closes an empty user account.
        </p>
        <KatanaNotes />
        <SolComposer deskAddress={SOL_FUNDED_WALLET_ADDRESS} />
      </main>
    </div>
  );
}
