"use client";

import { CopyButton } from "@/components/sol/copy-button";
import { solExplorerAccountUrl } from "@/lib/katana";

export function KatanaWalletDesk({
  address,
  connecting,
  sending,
  notice,
  onConnect,
  onDisconnect,
}: {
  address: string | null;
  connecting: boolean;
  sending: boolean;
  notice: string | null;
  onConnect: () => void;
  onDisconnect: () => void;
}) {
  const busy = connecting || sending;

  return (
    <section className="ton-wallet" aria-live="polite">
      {address ? (
        <div className="ton-wallet-row">
          <div>
            <p className="ton-kicker">Connected wallet · Solana</p>
            <p className="ton-address">{address}</p>
            <div className="ton-links">
              <CopyButton value={address} label="Copy address" />
              <a href={solExplorerAccountUrl(address)} target="_blank" rel="noreferrer">
                Solscan
              </a>
            </div>
          </div>
          <button
            type="button"
            className="ton-button ton-button-quiet"
            onClick={onDisconnect}
            disabled={busy}
          >
            Disconnect
          </button>
        </div>
      ) : (
        <div>
          <p className="ton-status">Connect a Solana browser wallet to continue.</p>
          <div className="ton-wallet-actions">
            <button
              type="button"
              className="ton-button ton-button-quiet"
              onClick={onConnect}
              disabled={busy}
            >
              {connecting ? "Connecting" : "Connect wallet"}
            </button>
          </div>
        </div>
      )}
      {address ? (
        <p className="ton-hint">Connected wallet must sign. It is the fee payer and the destination owner.</p>
      ) : null}
      {notice ? <p className="ton-status">{notice}</p> : null}
    </section>
  );
}
