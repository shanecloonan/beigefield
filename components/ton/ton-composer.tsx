"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import {
  useIsConnectionRestored,
  useTonAddress,
  useTonConnectUI,
  useTonWallet,
} from "@tonconnect/ui-react";
import {
  TonProvider,
  clearConnectNotice,
  reportConnectNotice,
  subscribeConnectNotice,
} from "@/components/ton/ton-provider";
import {
  chainLabel,
  classifySendError,
  connectFailureMessage,
  isMainnetChain,
  sendFailureMessage,
  validateMainnetTransfer,
  type FieldErrors,
} from "@/lib/ton-message";

type Notice =
  | {
      tone: "good";
      text: string;
      href: string;
      hrefLabel: string;
    }
  | {
      tone: "bad";
      text: string;
    }
  | null;

export function TonComposer({ manifestUrl }: { manifestUrl: string }) {
  return (
    <TonProvider manifestUrl={manifestUrl}>
      <TonForm manifestUrl={manifestUrl} />
    </TonProvider>
  );
}

function TonForm({ manifestUrl }: { manifestUrl: string }) {
  const [tonConnectUI] = useTonConnectUI();
  const wallet = useTonWallet();
  const address = useTonAddress();
  const restored = useIsConnectionRestored();
  const sendingRef = useRef(false);

  const [destination, setDestination] = useState("");
  const [amount, setAmount] = useState("");
  const [comment, setComment] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [notice, setNotice] = useState<Notice>(null);
  const [connectNotice, setConnectNotice] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const onMainnet = isMainnetChain(wallet?.account.chain);

  useEffect(() => subscribeConnectNotice(setConnectNotice), []);
  const preview = useMemo(
    () =>
      validateMainnetTransfer({
        destination,
        amountTon: amount,
        comment,
      }),
    [destination, amount, comment],
  );

  function clearField(field: keyof FieldErrors) {
    setErrors((current) =>
      current[field] ? { ...current, [field]: undefined } : current,
    );
    setNotice(null);
  }

  async function connect() {
    clearConnectNotice();
    try {
      await tonConnectUI.openModal();
    } catch (error) {
      reportConnectNotice(
        connectFailureMessage(classifySendError(error), manifestUrl),
      );
    }
  }

  async function disconnect() {
    clearConnectNotice();
    try {
      await tonConnectUI.disconnect();
    } catch (error) {
      reportConnectNotice(
        connectFailureMessage(classifySendError(error), manifestUrl) ??
          "The wallet could not be disconnected.",
      );
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sendingRef.current) return;

    const result = validateMainnetTransfer({
      destination,
      amountTon: amount,
      comment,
      fromRaw: wallet?.account.address,
    });

    if (!result.ok) {
      setErrors(result.errors);
      setNotice(null);
      return;
    }

    setErrors({});

    if (!restored || !wallet) {
      setNotice({
        tone: "bad",
        text: "Connect a mainnet wallet to send this transfer.",
      });
      return;
    }

    if (!isMainnetChain(wallet.account.chain)) {
      setNotice({
        tone: "bad",
        text: `This wallet is on ${chainLabel(wallet.account.chain)}. Switch it to TON mainnet and connect again. The transfer was not sent.`,
      });
      return;
    }

    sendingRef.current = true;
    setSending(true);
    setNotice(null);

    try {
      const response = await tonConnectUI.sendTransaction(result.request);
      if (!response?.boc) {
        setNotice({ tone: "bad", text: sendFailureMessage("ambiguous") });
        return;
      }
      const sentTo = result.request.messages[0].address;
      setNotice({
        tone: "good",
        text: `Sent on mainnet. ${amount.trim()} TON to ${sentTo}.`,
        href: `https://tonviewer.com/${encodeURIComponent(sentTo)}`,
        hrefLabel: "View the destination on Tonviewer",
      });
    } catch (error) {
      setNotice({
        tone: "bad",
        text: sendFailureMessage(classifySendError(error)),
      });
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }

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
        <p className="ton-kicker">Mainnet</p>
        <h1>TON messages</h1>
        <p className="ton-lede">
          Compose a transfer on The Open Network main network. The connected
          wallet signs the message and broadcasts it.
        </p>

        <section className="ton-wallet" aria-live="polite">
          {!restored ? (
            <p className="ton-status">Checking for a connected wallet.</p>
          ) : wallet && onMainnet ? (
            <div className="ton-wallet-row">
              <div>
                <p className="ton-kicker">Connected · mainnet</p>
                <p className="ton-address">{address}</p>
              </div>
              <button
                type="button"
                className="ton-button ton-button-quiet"
                onClick={() => void disconnect()}
              >
                Disconnect
              </button>
            </div>
          ) : wallet ? (
            <div className="ton-wallet-row">
              <p className="ton-status">
                This wallet is on {chainLabel(wallet.account.chain)}. Switch it
                to TON mainnet and connect again.
              </p>
              <button
                type="button"
                className="ton-button ton-button-quiet"
                onClick={() => void disconnect()}
              >
                Disconnect
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="ton-button"
              onClick={() => void connect()}
            >
              Connect wallet
            </button>
          )}
          {connectNotice ? <p className="ton-status">{connectNotice}</p> : null}
        </section>

        <form className="ton-form" onSubmit={(event) => void onSubmit(event)} noValidate>
          <label className="ton-field">
            <span>Destination</span>
            <input
              name="destination"
              value={destination}
              onChange={(event) => {
                setDestination(event.target.value);
                clearField("destination");
              }}
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              placeholder="UQ…"
              aria-invalid={Boolean(errors.destination)}
              aria-describedby="destination-hint"
            />
          </label>
          <p id="destination-hint" className="ton-hint">
            Mainnet address. Bounceable and non-bounceable forms are kept as
            written.
          </p>
          {errors.destination ? (
            <p className="ton-error" role="alert">
              {errors.destination}
            </p>
          ) : null}

          <label className="ton-field">
            <span>Amount</span>
            <span className="ton-amount">
              <input
                name="amount"
                value={amount}
                onChange={(event) => {
                  setAmount(event.target.value);
                  clearField("amount");
                }}
                inputMode="decimal"
                autoComplete="off"
                placeholder="0.1"
                aria-invalid={Boolean(errors.amount)}
                aria-describedby="amount-suffix"
              />
              <span id="amount-suffix">TON</span>
            </span>
          </label>
          {errors.amount ? (
            <p className="ton-error" role="alert">
              {errors.amount}
            </p>
          ) : null}

          <label className="ton-field">
            <span>Comment</span>
            <textarea
              name="comment"
              value={comment}
              onChange={(event) => {
                setComment(event.target.value);
                clearField("comment");
              }}
              rows={3}
              placeholder="Optional note"
              aria-invalid={Boolean(errors.comment)}
              aria-describedby="comment-hint"
            />
          </label>
          <p id="comment-hint" className="ton-hint">
            Optional text included with the transfer.
          </p>
          {errors.comment ? (
            <p className="ton-error" role="alert">
              {errors.comment}
            </p>
          ) : null}

          {preview.ok ? (
            <p className="ton-preview">
              Mainnet transfer of {amount.trim()} TON to{" "}
              {preview.request.messages[0].address}
              {preview.request.messages[0].payload
                ? ", with a text comment"
                : ""}
              .
            </p>
          ) : null}

          <div className="ton-submit" aria-live="polite">
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
            <button
              type="submit"
              className="ton-button"
              disabled={!restored || sending || Boolean(wallet && !onMainnet)}
            >
              {sending ? "Waiting for the wallet" : "Send on mainnet"}
            </button>
            <p className="ton-hint">Mainnet transfers are final.</p>
          </div>
        </form>
      </main>
    </div>
  );
}
