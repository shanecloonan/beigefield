"use client";

import "@/lib/buffer-polyfill";
import { PublicKey, Transaction } from "@solana/web3.js";
import { useEffect, useRef, useState } from "react";
import type { PathNotice } from "@/components/sol/path-run-bar";
import { KatanaWalletDesk } from "@/components/katana/wallet-desk";
import { WithdrawBar } from "@/components/katana/withdraw-bar";
import {
  DEFAULT_KATANA_VAULT,
  KATANA_VAULTS,
  katanaVaultLabel,
  readBaseUnits,
  solExplorerAccountUrl,
  solExplorerTxUrl,
} from "@/lib/katana";
import {
  authorizedSendError,
  buildAuthorizedInstantWithdraw,
  formatTokenAmount,
  readAuthorizedBlockhash,
  readAuthorizedLookup,
  snapshotFromAuthorizedLookup,
  type KatanaAuthorizedLookupOk,
} from "@/lib/katana-authorized";
import { getSolanaProvider, readWalletSignature, type SolanaInjectedProvider } from "@/lib/sol-browser-wallet";
import { isSolAddress } from "@/lib/sol-funded-wallet-public";

export function KatanaComposer() {
  const [address, setAddress] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [deskNotice, setDeskNotice] = useState<string | null>(null);
  const [state, setState] = useState(DEFAULT_KATANA_VAULT);
  const [amountText, setAmountText] = useState("");
  const [lookup, setLookup] = useState<KatanaAuthorizedLookupOk | null>(null);
  const [lookupNote, setLookupNote] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<PathNotice | null>(null);
  const sendingRef = useRef(false);
  const amountRef = useRef(amountText);
  const stateRef = useRef(state);
  const addressRef = useRef(address);
  amountRef.current = amountText;
  stateRef.current = state;
  addressRef.current = address;

  useEffect(() => {
    const provider = getSolanaProvider();
    if (!provider) return;
    let cancel = false;

    function applyKey(publicKey: { toBase58(): string } | null | undefined) {
      if (cancel) return;
      const next = publicKey?.toBase58() ?? null;
      setAddress(next && isSolAddress(next) ? next : null);
      if (!next) setLookup(null);
    }

    void provider.connect({ onlyIfTrusted: true }).then(
      (result) => applyKey(result.publicKey),
      () => undefined,
    );

    const onAccount = (publicKey?: { toBase58(): string } | null) => applyKey(publicKey ?? null);
    const onDisconnect = () => applyKey(null);
    provider.on?.("accountChanged", onAccount);
    provider.on?.("disconnect", onDisconnect);
    return () => {
      cancel = true;
      provider.off?.("accountChanged", onAccount);
      provider.off?.("disconnect", onDisconnect);
      provider.removeListener?.("accountChanged", onAccount);
      provider.removeListener?.("disconnect", onDisconnect);
    };
  }, []);

  useEffect(() => {
    if (!address) {
      setLookup(null);
      setLookupNote("Connect a Solana wallet to look up your pending deposit.");
      setAmountText("");
      return;
    }
    let cancel = false;
    void (async () => {
      const defaults = await fetchAuthorizedLookup(address, state);
      if (cancel) return;
      if (!defaults) {
        setLookup(null);
        setLookupNote("The RPC lookup did not answer.");
        return;
      }
      if (!defaults.ok) {
        setLookup(null);
        setLookupNote(defaults.message);
        return;
      }
      if (defaults.owner !== address) {
        setLookup(null);
        setLookupNote("The lookup owner does not match the connected wallet.");
        return;
      }
      setLookup(defaults);
      setLookupNote(defaults.note);
      if (defaults.withdrawable) {
        setAmountText(defaults.deposit_amount);
      } else {
        setAmountText("");
      }
    })();
    return () => {
      cancel = true;
    };
  }, [address, state]);

  async function connectWallet() {
    const provider = getSolanaProvider();
    if (!provider) {
      setDeskNotice("Install a Solana browser wallet such as Phantom, then connect it here.");
      return;
    }
    setConnecting(true);
    setDeskNotice(null);
    setNotice(null);
    try {
      const result = await provider.connect();
      const next = result.publicKey.toBase58();
      if (!isSolAddress(next)) {
        setDeskNotice("The wallet did not return a Solana address.");
        return;
      }
      setAddress(next);
    } catch (error) {
      setDeskNotice(authorizedSendError(error));
    } finally {
      setConnecting(false);
    }
  }

  async function disconnectWallet() {
    const provider = getSolanaProvider();
    try {
      await provider?.disconnect();
    } catch {
      // The local session is cleared either way.
    }
    setAddress(null);
    setLookup(null);
    setNotice(null);
    setDeskNotice(null);
  }

  async function runWithdraw() {
    if (sendingRef.current) return;
    const connected = addressRef.current;
    if (!connected || !isSolAddress(connected)) {
      setNotice({ tone: "bad", text: "Connect a Solana wallet. Nothing was sent." });
      return;
    }
    const provider = getSolanaProvider();
    if (!provider) {
      setNotice({ tone: "bad", text: "Install a Solana browser wallet such as Phantom. Nothing was sent." });
      return;
    }
    const providerKey = provider.publicKey?.toBase58() ?? "";
    if (providerKey !== connected) {
      setNotice({ tone: "bad", text: "The connected wallet must be the depositor and the fee payer. Nothing was sent." });
      return;
    }

    sendingRef.current = true;
    setSending(true);
    setNotice(null);
    try {
      const defaults = await fetchAuthorizedLookup(connected, stateRef.current);
      if (!defaults) {
        setNotice({ tone: "bad", text: "The RPC lookup did not answer. Nothing was sent." });
        return;
      }
      if (!defaults.ok) {
        setNotice({ tone: "bad", text: `${defaults.message} Nothing was sent.` });
        return;
      }
      if (defaults.owner !== connected || defaults.user_owner !== connected) {
        setNotice({ tone: "bad", text: "The connected wallet must be the depositor and the fee payer. Nothing was sent." });
        return;
      }
      setLookup(defaults);
      setLookupNote(defaults.note);

      const built = buildAuthorizedInstantWithdraw({
        connectedOwner: connected,
        snapshot: snapshotFromAuthorizedLookup(defaults),
        amount: amountRef.current,
      });
      if (!built.ok) {
        setNotice({ tone: "bad", text: built.message });
        return;
      }

      const latest = await fetchAuthorizedBlockhash();
      if (!latest) {
        setNotice({ tone: "bad", text: "The RPC did not return a recent blockhash. Nothing was sent." });
        return;
      }
      if (!latest.ok) {
        setNotice({ tone: "bad", text: `${latest.message} Nothing was sent.` });
        return;
      }

      const owner = new PublicKey(connected);
      const tx = new Transaction();
      tx.feePayer = owner;
      tx.recentBlockhash = latest.blockhash;
      tx.add(...built.instructions);
      if (!tx.feePayer.equals(owner)) {
        setNotice({ tone: "bad", text: "The connected wallet must be the depositor and the fee payer. Nothing was sent." });
        return;
      }

      const signature = await signAndSend(provider, tx);
      if (!signature) {
        setNotice({
          tone: "bad",
          text: "The send reply could not be read. Check the account before trying again, so it is not sent twice.",
        });
        return;
      }
      setNotice({
        tone: "good",
        text: `Broadcast ${signature}.`,
        href: solExplorerTxUrl(signature),
        hrefLabel: "View the transaction",
      });
    } catch (error) {
      setNotice({ tone: "bad", text: authorizedSendError(error) });
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }

  const parsedAmount = readBaseUnits(amountText);
  const pending = lookup ? readBaseUnits(lookup.deposit_amount) ?? BigInt(0) : BigInt(0);
  const amountOk =
    parsedAmount !== null && lookup?.withdrawable === true && parsedAmount <= pending;
  const runDisabled =
    sending ||
    connecting ||
    !address ||
    !lookup ||
    !lookup.withdrawable ||
    lookup.paused ||
    lookup.owner !== address ||
    !amountOk;

  return (
    <section className="ton-section" id="message" aria-labelledby="ton-message-title">
      <h2 id="ton-message-title">Your pending amount</h2>
      <nav className="ton-contents" aria-label="Withdraw">
        <a href="#wallet">Connected wallet</a>
        <a href="#withdraw">Withdraw pending deposit</a>
      </nav>
      <div id="wallet">
        <KatanaWalletDesk
          address={address}
          connecting={connecting}
          sending={sending}
          notice={deskNotice}
          onConnect={() => void connectWallet()}
          onDisconnect={() => void disconnectWallet()}
        />
      </div>
      <label className="ton-field">
        <span>Katana vault</span>
        <select
          aria-label="Katana vault"
          value={state}
          onChange={(event) => {
            setState(event.target.value);
            setNotice(null);
          }}
        >
          {KATANA_VAULTS.map((vault) => (
            <option key={vault.state} value={vault.state}>
              {katanaVaultLabel(vault)}
            </option>
          ))}
        </select>
      </label>
      {lookup ? <PendingFields lookup={lookup} /> : null}
      <label className="ton-field">
        <span>Your pending amount</span>
        <input
          inputMode="numeric"
          autoComplete="off"
          aria-label="Your pending amount"
          value={amountText}
          onChange={(event) => {
            setAmountText(event.target.value);
            setNotice(null);
          }}
          disabled={!lookup?.withdrawable}
        />
      </label>
      <WithdrawBar
        sending={sending}
        label={sending ? "Sending" : "Withdraw pending deposit"}
        disabled={runDisabled}
        notice={notice}
        lookupNote={lookupNote}
        onRun={() => void runWithdraw()}
      />
    </section>
  );
}

function PendingFields({ lookup }: { lookup: KatanaAuthorizedLookupOk }) {
  const pending = BigInt(lookup.deposit_amount);
  const human = formatTokenAmount(pending, lookup.decimals);
  return (
    <dl className="ton-preview-list">
      <div>
        <dt>Vault round</dt>
        <dd>{lookup.vault_round}</dd>
      </div>
      <div>
        <dt>Deposit round</dt>
        <dd>{lookup.deposit_round ?? "None"}</dd>
      </div>
      <div>
        <dt>Pending</dt>
        <dd>
          {human} {lookup.label}
          <span className="ton-preview-nano"> · {lookup.deposit_amount} base units</span>
        </dd>
      </div>
      <div>
        <dt>Underlying mint</dt>
        <dd>
          <a href={solExplorerAccountUrl(lookup.underlying_mint)} target="_blank" rel="noreferrer">
            {lookup.underlying_mint}
          </a>
        </dd>
      </div>
      <div>
        <dt>Your token account</dt>
        <dd>
          <a href={solExplorerAccountUrl(lookup.destination_ata)} target="_blank" rel="noreferrer">
            {lookup.destination_ata}
          </a>
        </dd>
      </div>
    </dl>
  );
}

async function fetchAuthorizedLookup(
  owner: string,
  state: string,
): Promise<KatanaAuthorizedLookupOk | { ok: false; message: string } | null> {
  try {
    const response = await fetch("/api/katana/lookup", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ owner, state }),
    });
    const payload: unknown = await response.json().catch(() => null);
    return readAuthorizedLookup(payload);
  } catch {
    return null;
  }
}

async function fetchAuthorizedBlockhash() {
  try {
    const response = await fetch("/api/katana/blockhash", { method: "GET" });
    const payload: unknown = await response.json().catch(() => null);
    return readAuthorizedBlockhash(payload);
  } catch {
    return null;
  }
}

async function signAndSend(provider: SolanaInjectedProvider, tx: Transaction): Promise<string | null> {
  if (typeof provider.signAndSendTransaction !== "function") {
    throw new Error("This wallet cannot send the transaction.");
  }
  return readWalletSignature(await provider.signAndSendTransaction(tx));
}
