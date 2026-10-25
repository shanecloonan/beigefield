"use client";

import { CopyButton } from "@/components/tons/copy-button";

export function tonsStepSendDisabled(input: {
  sending: boolean;
  localWallet: boolean;
  restored: boolean;
  walletOnWrongChain: boolean;
}): boolean {
  return (
    input.sending ||
    (!input.localWallet && (!input.restored || input.walletOnWrongChain))
  );
}

export function tonsInFlightLabel(localWallet: boolean): string {
  return localWallet ? "Sending" : "Waiting for the wallet";
}

export function TonsWalletDesk({
  localWallet,
  restored,
  connected,
  onMainnet,
  address,
  chainName,
  sending,
  connectNotice,
  fundedAddress,
  onUseFunded,
  onClearFunded,
  onConnect,
  onDisconnect,
}: {
  localWallet: boolean;
  restored: boolean;
  connected: boolean;
  onMainnet: boolean;
  address: string;
  chainName: string;
  sending: boolean;
  connectNotice: string | null;
  fundedAddress: string;
  onUseFunded: () => void;
  onClearFunded: () => void;
  onConnect: () => void;
  onDisconnect: () => void;
}) {
  return (
    <section className="ton-wallet" aria-live="polite">
      {localWallet ? (
        <div className="ton-wallet-row">
          <div>
            <p className="ton-kicker">Local wallet · mainnet</p>
            <p className="ton-address">{fundedAddress}</p>
            <div className="ton-links">
              <CopyButton value={fundedAddress} label="Copy address" />
              <a
                href={`https://tonviewer.com/${encodeURIComponent(fundedAddress)}`}
                target="_blank"
                rel="noreferrer"
              >
                Tonviewer
              </a>
            </div>
          </div>
          <button
            type="button"
            className="ton-button ton-button-quiet"
            onClick={onClearFunded}
            disabled={sending}
          >
            Disconnect
          </button>
        </div>
      ) : !restored ? (
        <div>
          <p className="ton-status">Checking for a connected wallet.</p>
          <div className="ton-wallet-actions">
            <button type="button" className="ton-button ton-button-quiet" onClick={onUseFunded}>
              Use funded wallet
            </button>
          </div>
        </div>
      ) : connected && onMainnet ? (
        <div className="ton-wallet-row">
          <div>
            <p className="ton-kicker">Connected · mainnet</p>
            <p className="ton-address">{address}</p>
            {address ? (
              <div className="ton-links">
                <CopyButton value={address} label="Copy address" />
                <a
                  href={`https://tonviewer.com/${encodeURIComponent(address)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Tonviewer
                </a>
              </div>
            ) : null}
          </div>
          <div className="ton-wallet-actions">
            <button
              type="button"
              className="ton-button ton-button-quiet"
              onClick={onUseFunded}
              disabled={sending}
            >
              Use funded wallet
            </button>
            <button
              type="button"
              className="ton-button ton-button-quiet"
              onClick={onDisconnect}
              disabled={sending}
            >
              Disconnect
            </button>
          </div>
        </div>
      ) : connected ? (
        <div className="ton-wallet-row">
          <div>
            <p className="ton-status">
              This wallet is on {chainName}. Switch it to TON mainnet and connect again.
            </p>
          </div>
          <div className="ton-wallet-actions">
            <button type="button" className="ton-button ton-button-quiet" onClick={onUseFunded}>
              Use funded wallet
            </button>
            <button type="button" className="ton-button ton-button-quiet" onClick={onDisconnect}>
              Disconnect
            </button>
          </div>
        </div>
      ) : (
        <div>
          <div className="ton-wallet-actions">
            <button type="button" className="ton-button" onClick={onConnect}>
              Connect wallet
            </button>
            <button type="button" className="ton-button ton-button-quiet" onClick={onUseFunded}>
              Use funded wallet
            </button>
          </div>
          <p className="ton-hint">
            Mainnet only. A testnet wallet is refused. Use funded wallet sends from the desk
            wallet without TonConnect.
          </p>
        </div>
      )}
      {localWallet ? (
        <p className="ton-hint">
          Signs on the server and broadcasts on mainnet. Disconnect to use TonConnect instead.
        </p>
      ) : null}
      {connectNotice ? <p className="ton-status">{connectNotice}</p> : null}
    </section>
  );
}
