"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Address } from "@ton/core";
import { CopyButton } from "@/components/tons/copy-button";
import { FUNDED_WALLET_ADDRESS } from "@/lib/funded-wallet-public";
import { readFundedSendResult, sendFailureMessage, type MainnetScriptRequest } from "@/lib/ton-message";
import {
  deskLookupNote,
  parseUtonAmount,
  readPathDefaultsPayload,
  runDeskBurn,
  type PathDefaultsRead,
} from "@/lib/uton-burn-desk";

type Notice =
  | { tone: "good"; text: string; href: string; hrefLabel: string }
  | { tone: "bad"; text: string };

export function BurnDesk() {
  const fundedRaw = useMemo(() => Address.parse(FUNDED_WALLET_ADDRESS).toRawString(), []);
  const sendingRef = useRef(false);
  const [amount, setAmount] = useState("");
  const [sending, setSending] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [lookupNote, setLookupNote] = useState("Looking up the desk uTON wallet.");

  useEffect(() => {
    let cancel = false;
    void (async () => {
      const read = await fetchPathDefaults();
      if (cancel) return;
      setLookupNote(deskLookupNote(read));
    })();
    return () => {
      cancel = true;
    };
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sendingRef.current) return;
    const parsed = parseUtonAmount(amount);
    if (!parsed.ok) {
      setNotice({ tone: "bad", text: `${parsed.message} Nothing was sent.` });
      return;
    }

    sendingRef.current = true;
    setSending(true);
    setNotice(null);
    setProgress("Sending");
    try {
      const read = await fetchPathDefaults();
      setLookupNote(deskLookupNote(read));
      if (!read?.ok) {
        setNotice({
          tone: "bad",
          text: read?.message ?? "The lookup did not answer. Nothing was sent.",
        });
        return;
      }
      const result = await runDeskBurn({
        amountLabel: amount.trim(),
        nanotons: parsed.nanotons,
        jettonWallet: read.jettonWallet,
        proxyId: read.proxyId,
        fromRaw: fundedRaw,
        send: deliver,
        onBatch: (index, total) => {
          setProgress(total > 1 ? `Sending ${index + 1} of ${total}` : "Sending");
        },
      });
      if (!result.ok) {
        setNotice({ tone: "bad", text: result.text });
        return;
      }
      setNotice({
        tone: "good",
        text: result.text,
        href: result.href,
        hrefLabel: "View the destination on Tonviewer",
      });
    } finally {
      sendingRef.current = false;
      setSending(false);
      setProgress(null);
    }
  }

  const buttonLabel = sending ? (progress ?? "Sending") : "Burn to redeem";

  return (
    <>
      <section className="ton-wallet" aria-label="Desk wallet">
        <div>
          <p className="ton-kicker">Desk wallet · mainnet</p>
          <p className="ton-address">{FUNDED_WALLET_ADDRESS}</p>
          <div className="ton-links">
            <CopyButton value={FUNDED_WALLET_ADDRESS} label="Copy address" />
            <a
              href={`https://tonviewer.com/${encodeURIComponent(FUNDED_WALLET_ADDRESS)}`}
              target="_blank"
              rel="noreferrer"
            >
              Tonviewer
            </a>
          </div>
        </div>
        <p className="ton-hint">
          Signs on the server and broadcasts on mainnet. This page sends from the desk wallet.
        </p>
      </section>
      <form className="ton-form" onSubmit={(event) => void onSubmit(event)}>
        <label className="ton-field" htmlFor="burn-amount">
          <span>uTON to burn</span>
          <span className="ton-amount">
            <input
              id="burn-amount"
              name="amount"
              inputMode="decimal"
              autoComplete="off"
              spellCheck={false}
              placeholder="1"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              disabled={sending}
              aria-describedby="burn-amount-hint"
            />
            <span>uTON</span>
          </span>
        </label>
        <p className="ton-hint" id="burn-amount-hint">
          Up to 9 decimal places. 1 uTON is 1000000000 nanotons. Gas is attached from the desk
          wallet: 0.2 TON on each burn, 0.15 TON on each notification, and 0.5 TON on the minter
          query that follows.
        </p>
        <button
          type="submit"
          className="ton-button ton-button-lead ton-submit"
          disabled={sending}
          aria-busy={sending}
        >
          {buttonLabel}
        </button>
        <div aria-live="polite">
          {lookupNote ? (
            <p className="ton-hint" role="status">
              {lookupNote}
            </p>
          ) : null}
          {notice ? (
            <p className={notice.tone === "good" ? "ton-good" : "ton-error"} role="status">
              {notice.text}{" "}
              {notice.tone === "good" ? (
                <a href={notice.href} target="_blank" rel="noreferrer">
                  {notice.hrefLabel}
                </a>
              ) : null}
            </p>
          ) : null}
        </div>
      </form>
    </>
  );
}

async function deliver(
  request: MainnetScriptRequest,
): Promise<{ ok: true } | { ok: false; text: string }> {
  try {
    const response = await fetch("/api/ton/send", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
    });
    const payload: unknown = await response.json().catch(() => null);
    const funded = readFundedSendResult(payload);
    if (funded) return funded;
    return { ok: false, text: sendFailureMessage("ambiguous") };
  } catch {
    return { ok: false, text: sendFailureMessage("ambiguous") };
  }
}

async function fetchPathDefaults(): Promise<PathDefaultsRead | null> {
  try {
    const response = await fetch(
      `/api/ton/path-defaults?owner=${encodeURIComponent(FUNDED_WALLET_ADDRESS)}`,
    );
    return readPathDefaultsPayload(await response.json());
  } catch {
    return null;
  }
}
