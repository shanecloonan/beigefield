"use client";

import { useEffect, useRef, useState } from "react";
import { PathRunBar, type PathNotice } from "@/components/sol/path-run-bar";
import { SourceList } from "@/components/sol/source-block";
import { SolWalletDesk, solInFlightLabel } from "@/components/sol/wallet-desk";
import {
  DEFAULT_KATANA_VAULT,
  KATANA_ACTION_LABELS,
  KATANA_ACTIONS,
  KATANA_VAULTS,
  katanaActionNeedsAmount,
  katanaVaultLabel,
  solExplorerTxUrl,
  type KatanaAction,
} from "@/lib/katana";
import { katanaPathSource } from "@/lib/katana-path";
import {
  compilePathRun,
  pathLookupNote,
  readKatanaPathDefaults,
  readKatanaSendResult,
  type KatanaPathDefaultsOk,
} from "@/lib/katana-path-run";
import { isSolAddress, SOL_FUNDED_WALLET_ADDRESS } from "@/lib/sol-funded-wallet-public";

export function SolComposer({ deskAddress }: { deskAddress: string }) {
  const initial = deskAddress.trim() || SOL_FUNDED_WALLET_ADDRESS;
  const [localWallet, setLocalWallet] = useState(true);
  const [address, setAddress] = useState(initial);
  const [sending, setSending] = useState(false);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [notice, setNotice] = useState<PathNotice | null>(null);
  const [lookupNote, setLookupNote] = useState<string | null>(null);
  const [deskNotice, setDeskNotice] = useState<string | null>(null);
  const [state, setState] = useState(DEFAULT_KATANA_VAULT);
  const [action, setAction] = useState<KatanaAction>("exit");
  const [amountText, setAmountText] = useState("");
  const sendingRef = useRef(false);
  const touchedAction = useRef(false);
  const actionRef = useRef<KatanaAction>(action);
  const amountRef = useRef(amountText);
  actionRef.current = action;
  amountRef.current = amountText;

  useEffect(() => {
    let cancel = false;
    void (async () => {
      const defaults = await fetchPathDefaults(address, state);
      if (cancel || !defaults) {
        if (!cancel) setLookupNote("The RPC lookup did not answer.");
        return;
      }
      if (!defaults.ok) {
        setLookupNote(defaults.message);
        return;
      }
      if (defaults.owner && isSolAddress(defaults.owner) && defaults.owner !== address) {
        setAddress(defaults.owner);
      }
      if (!touchedAction.current && defaults.suggested) {
        setAction(defaults.suggested);
        if (defaults.suggested === "instant_withdraw" && defaults.user_deposit !== "0") {
          setAmountText(defaults.user_deposit);
        }
      }
      setLookupNote(
        pathLookupNote({
          expired: defaults.expired,
          paused: defaults.paused,
          round: defaults.round,
          suggested: defaults.suggested,
          userDeposit: defaults.user_deposit,
          userUnredeemed: defaults.user_unredeemed,
          userWithdrawShares: defaults.user_withdraw_shares,
          userDerivative: defaults.user_derivative,
          lamports: defaults.lamports,
        }),
      );
    })();
    return () => {
      cancel = true;
    };
  }, [localWallet, address, state]);

  async function runPath() {
    if (sendingRef.current) return;
    if (!localWallet) {
      setNotice({ tone: "bad", text: "The desk wallet is the only signer. Nothing was sent." });
      return;
    }
    sendingRef.current = true;
    setSending(true);
    setSendingId("path");
    setNotice(null);
    try {
      const defaults = await fetchPathDefaults(address, state);
      if (!defaults) {
        setNotice({ tone: "bad", text: "The RPC lookup did not answer. Nothing was sent." });
        return;
      }
      if (!defaults.ok) {
        setNotice({ tone: "bad", text: `${defaults.message} Nothing was sent.` });
        return;
      }
      setLookupNote(
        pathLookupNote({
          expired: defaults.expired,
          paused: defaults.paused,
          round: defaults.round,
          suggested: defaults.suggested,
          userDeposit: defaults.user_deposit,
          userUnredeemed: defaults.user_unredeemed,
          userWithdrawShares: defaults.user_withdraw_shares,
          userDerivative: defaults.user_derivative,
          lamports: defaults.lamports,
        }),
      );
      const chosen = actionRef.current;
      const compiled = compilePathRun({
        sender: address,
        state,
        action: chosen,
        amount: katanaActionNeedsAmount(chosen) ? amountRef.current : undefined,
      });
      if (!compiled.ok) {
        setNotice({ tone: "bad", text: compiled.message });
        return;
      }
      const response = await fetch("/api/sol/send", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          sender: compiled.sender,
          state: compiled.state,
          action: compiled.action,
          ...(compiled.amount ? { amount: compiled.amount } : {}),
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
      setSendingId(null);
    }
  }

  const needsAmount = katanaActionNeedsAmount(action);
  const pathDisabled =
    sending || !localWallet || !isSolAddress(address) || (needsAmount && !/^\d+$/.test(amountText.trim()));

  return (
    <section className="ton-section" id="message" aria-labelledby="ton-message-title">
      <h2 id="ton-message-title">Path</h2>
      <nav className="ton-contents" aria-label="Path">
        <a href="#path-run">Run path</a>
        <a href="#claim-shares">claim_shares</a>
        <a href="#withdraw-expired">withdraw_expired</a>
        <a href="#complete-withdraw">complete_withdraw</a>
        <a href="#instant-withdraw">instant_withdraw</a>
        <a href="#omitted">Not sent</a>
      </nav>
      <SolWalletDesk
        localWallet={localWallet}
        address={address}
        sending={sending}
        notice={deskNotice}
        onUseFunded={() => {
          setLocalWallet(true);
          setDeskNotice(null);
        }}
        onDisconnect={() => {
          setLocalWallet(false);
          setDeskNotice("The desk wallet is the only signer.");
        }}
      />
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
      <label className="ton-field">
        <span>instruction</span>
        <select
          aria-label="Katana instruction"
          value={action}
          onChange={(event) => {
            touchedAction.current = true;
            setAction(event.target.value as KatanaAction);
            setNotice(null);
          }}
        >
          {KATANA_ACTIONS.map((item) => (
            <option key={item} value={item}>
              {KATANA_ACTION_LABELS[item]}
            </option>
          ))}
        </select>
      </label>
      {needsAmount ? (
        <label className="ton-field">
          <span>amount_underlying</span>
          <input
            inputMode="numeric"
            autoComplete="off"
            aria-label="amount_underlying"
            value={amountText}
            onChange={(event) => {
              setAmountText(event.target.value);
              setNotice(null);
            }}
          />
        </label>
      ) : null}
      <PathRunBar
        sending={sendingId === "path"}
        label={sendingId === "path" ? solInFlightLabel() : "Run path"}
        disabled={pathDisabled}
        notice={notice}
        lookupNote={lookupNote}
        onRun={() => void runPath()}
      />
      <div className="ton-steps">
        <PathCards />
      </div>
    </section>
  );
}

export function PathCards() {
  return (
    <>
      <ReadOnlyCard
        id="claim-shares"
        titleId="claim-shares-title"
        kicker="Katana"
        title="claim_shares"
        sources={[katanaPathSource.claimShares]}
        hint="Mints vault shares for a pending deposit that has already been rolled. Needed before withdraw_expired when unredeemedShares is positive."
      />
      <ReadOnlyCard
        id="withdraw-expired"
        titleId="withdraw-expired-title"
        kicker="Katana"
        title="withdraw_expired"
        sources={[katanaPathSource.withdrawExpired]}
        hint="Burns claimed shares for the underlying once the vault State reports isExpired. This is the instruction recent mainnet exits still land."
      />
      <ReadOnlyCard
        id="complete-withdraw"
        titleId="complete-withdraw-title"
        kicker="Katana"
        title="complete_withdraw"
        sources={[katanaPathSource.completeWithdraw]}
        hint="Finishes a withdrawal that was queued with initiate_withdraw in an earlier round."
      />
      <ReadOnlyCard
        id="instant-withdraw"
        titleId="instant-withdraw-title"
        kicker="Katana"
        title="instant_withdraw"
        sources={[katanaPathSource.instantWithdraw]}
        hint="Returns a pending deposit that was never rolled into a round. amount_underlying is in base units of the vault's underlying mint."
      />
      <ReadOnlyCard
        id="omitted"
        titleId="omitted-title"
        kicker="Katana"
        title="Not sent"
        sources={[katanaPathSource.closeUser, katanaPathSource.omitted]}
        hint="close_user_account recovers rent on an empty user account. Deposit and migrate are listed so they are not mistaken for remaining actions."
      />
    </>
  );
}

function ReadOnlyCard({
  id,
  titleId,
  kicker,
  title,
  sources,
  hint,
}: {
  id: string;
  titleId: string;
  kicker: string;
  title: string;
  sources: readonly { file: string; code: string }[];
  hint: string;
}) {
  return (
    <section className="ton-step" id={id} aria-labelledby={titleId}>
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">{kicker}</p>
          <h2 id={titleId}>{title}</h2>
        </div>
      </div>
      <SourceList sources={sources} />
      <p className="ton-hint">{hint}</p>
    </section>
  );
}

async function fetchPathDefaults(
  owner: string,
  state: string,
): Promise<KatanaPathDefaultsOk | { ok: false; message: string } | null> {
  try {
    const response = await fetch("/api/sol/path-defaults", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ owner, state }),
    });
    const payload: unknown = await response.json().catch(() => null);
    return readKatanaPathDefaults(payload);
  } catch {
    return null;
  }
}
