"use client";

import "@/lib/buffer-polyfill";
import { useEffect, useRef, useState } from "react";
import type { PathNotice } from "@/components/sol/path-run-bar";
import { KatanaWalletDesk, katanaInFlightLabel } from "@/components/katana/wallet-desk";
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
  buildAuthorizedInstantWithdraw,
  formatTokenAmount,
  readAuthorizedLookup,
  snapshotFromAuthorizedLookup,
  type KatanaAuthorizedLookupOk,
} from "@/lib/katana-authorized";
import { readKatanaSendResult } from "@/lib/katana-path-run";
import { isSolAddress, SOL_FUNDED_WALLET_ADDRESS } from "@/lib/sol-funded-wallet-public";

export function KatanaComposer({ deskAddress }: { deskAddress: string }) {
  const initial = deskAddress.trim() || SOL_FUNDED_WALLET_ADDRESS;
  const [localWallet, setLocalWallet] = useState(true);
  const [address, setAddress] = useState(initial);
  const [deskNotice, setDeskNotice] = useState<string | null>(null);
  const [state, setState] = useState(DEFAULT_KATANA_VAULT);
  const [userAuthority, setUserAuthority] = useState("");
  const [destination, setDestination] = useState(initial);
  const [amountText, setAmountText] = useState("");
  const [lookup, setLookup] = useState<KatanaAuthorizedLookupOk | null>(null);
  const [lookupNote, setLookupNote] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<PathNotice | null>(null);
  const sendingRef = useRef(false);
  const amountRef = useRef(amountText);
  const stateRef = useRef(state);
  const addressRef = useRef(address);
  const userAuthorityRef = useRef(userAuthority);
  const destinationRef = useRef(destination);
  amountRef.current = amountText;
  stateRef.current = state;
  addressRef.current = address;
  userAuthorityRef.current = userAuthority;
  destinationRef.current = destination;

  useEffect(() => {
    if (!isSolAddress(userAuthority)) {
      setLookup(null);
      setLookupNote(
        userAuthority.trim()
          ? "Enter a valid user authority."
          : "Enter a user authority to look up the pending deposit.",
      );
      setAmountText("");
      return;
    }
    let cancel = false;
    void (async () => {
      const defaults = await fetchAuthorizedLookup(userAuthority, state);
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
      if (defaults.owner !== userAuthority) {
        setLookup(null);
        setLookupNote("The lookup user authority does not match.");
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
  }, [localWallet, userAuthority, state]);

  async function runWithdraw() {
    if (sendingRef.current) return;
    if (!localWallet) {
      setNotice({ tone: "bad", text: "The desk wallet is the only signer. Nothing was sent." });
      return;
    }
    const feePayer = addressRef.current;
    const authority = userAuthorityRef.current;
    const dest = destinationRef.current;
    if (!isSolAddress(feePayer)) {
      setNotice({ tone: "bad", text: "The desk wallet is unset. Nothing was sent." });
      return;
    }
    if (!isSolAddress(authority)) {
      setNotice({ tone: "bad", text: "Enter a user authority. Nothing was sent." });
      return;
    }
    if (!isSolAddress(dest)) {
      setNotice({ tone: "bad", text: "Enter a destination token account. Nothing was sent." });
      return;
    }

    sendingRef.current = true;
    setSending(true);
    setNotice(null);
    try {
      const defaults = await fetchAuthorizedLookup(authority, stateRef.current);
      if (!defaults) {
        setNotice({ tone: "bad", text: "The RPC lookup did not answer. Nothing was sent." });
        return;
      }
      if (!defaults.ok) {
        setNotice({ tone: "bad", text: `${defaults.message} Nothing was sent.` });
        return;
      }
      if (defaults.owner !== authority) {
        setNotice({ tone: "bad", text: "The lookup user authority does not match. Nothing was sent." });
        return;
      }
      setLookup(defaults);
      setLookupNote(defaults.note);

      const built = buildAuthorizedInstantWithdraw({
        feePayer,
        userAuthority: authority,
        destination: dest,
        snapshot: snapshotFromAuthorizedLookup(defaults),
        amount: amountRef.current,
      });
      if (!built.ok) {
        setNotice({ tone: "bad", text: built.message });
        return;
      }

      const response = await fetch("/api/katana/send", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          sender: feePayer,
          state: stateRef.current,
          userAuthority: authority,
          destination: dest,
          amount: amountRef.current,
        }),
      });
      const payload: unknown = await response.json().catch(() => null);
      const result = readKatanaSendResult(payload);
      if (!result) {
        setNotice({
          tone: "bad",
          text: "The send reply could not be read. Check the account before trying again, so it is not sent twice.",
        });
        return;
      }
      if (!result.ok) {
        setNotice({ tone: "bad", text: result.text });
        return;
      }
      setNotice({
        tone: "good",
        text: `Broadcast ${result.signature}.`,
        href: solExplorerTxUrl(result.signature),
        hrefLabel: "View the transaction",
      });
    } catch {
      setNotice({
        tone: "bad",
        text: "The send did not finish. Check the account before trying again, so it is not sent twice.",
      });
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
    !localWallet ||
    !isSolAddress(address) ||
    !lookup ||
    !lookup.withdrawable ||
    lookup.paused ||
    !isSolAddress(userAuthority) ||
    !isSolAddress(destination) ||
    !amountOk;

  return (
    <section className="ton-section" id="message" aria-labelledby="ton-message-title">
      <h2 id="ton-message-title">Your pending amount</h2>
      <nav className="ton-contents" aria-label="Withdraw">
        <a href="#wallet">Desk wallet</a>
        <a href="#user-authority">User authority</a>
        <a href="#destination">Destination</a>
        <a href="#withdraw">Withdraw pending deposit</a>
      </nav>
      <div id="wallet">
        <KatanaWalletDesk
          localWallet={localWallet}
          address={address}
          sending={sending}
          notice={deskNotice}
          onUseFunded={() => {
            setLocalWallet(true);
            setAddress(initial);
            setDestination(initial);
            setDeskNotice(null);
          }}
          onDisconnect={() => {
            setLocalWallet(false);
            setDeskNotice("The desk wallet is the only signer.");
          }}
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
      <label className="ton-field" id="user-authority">
        <span>User authority</span>
        <input
          autoComplete="off"
          spellCheck={false}
          aria-label="User authority"
          value={userAuthority}
          onChange={(event) => {
            setUserAuthority(event.target.value.trim());
            setNotice(null);
          }}
        />
      </label>
      <label className="ton-field" id="destination">
        <span>Destination token account</span>
        <input
          autoComplete="off"
          spellCheck={false}
          aria-label="Destination token account"
          value={destination}
          onChange={(event) => {
            setDestination(event.target.value.trim());
            setNotice(null);
          }}
        />
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
        label={sending ? katanaInFlightLabel() : "Withdraw pending deposit"}
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
        <dt>User account</dt>
        <dd>
          <a href={solExplorerAccountUrl(lookup.user_account)} target="_blank" rel="noreferrer">
            {lookup.user_account}
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
