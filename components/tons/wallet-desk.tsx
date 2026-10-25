"use client";

import { CopyButton } from "@/components/tons/copy-button";
import { zigExplorerAccountUrl } from "@/lib/valdora";

export function tonsInFlightLabel(): string {
  return "Sending";
}

export function TonsWalletDesk({
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
            <p className="ton-kicker">Local wallet · ZIGChain</p>
            <p className="ton-address">{address || "Desk address unset"}</p>
            {address ? (
              <div className="ton-links">
                <CopyButton value={address} label="Copy address" />
                <a href={zigExplorerAccountUrl(address)} target="_blank" rel="noreferrer">
                  ZIGChain explorer
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
        <p className="ton-hint">Signs on the server and broadcasts on ZIGChain.</p>
      ) : null}
      {notice ? <p className="ton-status">{notice}</p> : null}
    </section>
  );
}
