"use client";

import { CopyButton } from "@/components/sol/copy-button";
import { solExplorerAccountUrl } from "@/lib/katana";

export function katanaInFlightLabel(): string {
  return "Sending";
}

export function KatanaWalletDesk({
  localWallet,
  address,
  sending,
  notice,
  onUseFunded,
  onDisconnect,
}: {
  localWallet: boolean;
  address: string;
  sending: boolean;
  notice: string | null;
  onUseFunded: () => void;
  onDisconnect: () => void;
}) {
  return (
    <section className="ton-wallet" aria-live="polite">
      {localWallet ? (
        <div className="ton-wallet-row">
          <div>
            <p className="ton-kicker">Desk wallet · Solana</p>
            <p className="ton-address">{address || "Desk address unset"}</p>
            {address ? (
              <div className="ton-links">
                <CopyButton value={address} label="Copy address" />
                <a href={solExplorerAccountUrl(address)} target="_blank" rel="noreferrer">
                  Solscan
                </a>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            className="ton-button ton-button-quiet"
            onClick={onDisconnect}
            disabled={sending}
          >
            Disconnect
          </button>
        </div>
      ) : (
        <div>
          <p className="ton-status">The desk wallet is the only signer.</p>
          <div className="ton-wallet-actions">
            <button
              type="button"
              className="ton-button ton-button-quiet"
              onClick={onUseFunded}
              disabled={sending}
            >
              Use funded wallet
            </button>
          </div>
        </div>
      )}
      {localWallet ? (
        <p className="ton-hint">
          Signs on the server and broadcasts on Solana mainnet. The desk
          wallet pays the network fee. It does not have to be the depositor
          or the destination.
        </p>
      ) : null}
      {notice ? <p className="ton-status">{notice}</p> : null}
    </section>
  );
}
