"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  useIsConnectionRestored,
  useTonAddress,
  useTonConnectUI,
  useTonWallet,
} from "@tonconnect/ui-react";
import { ScriptStepCard } from "@/components/ton/script-step";
import {
  TonProvider,
  clearConnectNotice,
  reportConnectNotice,
  subscribeConnectNotice,
} from "@/components/ton/ton-provider";
import {
  chainLabel,
  classifySendError,
  compileScript,
  compileStep,
  connectFailureMessage,
  emptyStep,
  isMainnetChain,
  readMaxMessages,
  sendFailureMessage,
  type MainnetScriptRequest,
  type ScriptStep,
  type StepErrors,
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
  const [steps, setSteps] = useState<ScriptStep[]>(() => [emptyStep("step-1")]);
  const [attempted, setAttempted] = useState<Record<string, boolean>>({});
  const [notice, setNotice] = useState<Notice>(null);
  const [connectNotice, setConnectNotice] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const onMainnet = isMainnetChain(wallet?.account.chain);
  const limit = readMaxMessages(wallet?.device.features);
  const compiled = useMemo(() => steps.map((step) => compileStep(step)), [steps]);
  const overLimit = Boolean(limit && steps.length > limit.maxMessages);

  useEffect(() => subscribeConnectNotice(setConnectNotice), []);

  function updateStep(id: string, next: ScriptStep) {
    setSteps((current) => current.map((step) => (step.id === id ? next : step)));
    setNotice(null);
  }

  function moveStep(index: number, direction: -1 | 1) {
    setSteps((current) => {
      const target = index + direction;
      if (target < 0 || target >= current.length) return current;
      const next = current.slice();
      const item = next[index];
      const swap = next[target];
      if (!item || !swap) return current;
      next[index] = swap;
      next[target] = item;
      return next;
    });
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

  async function transmit(request: MainnetScriptRequest, text: string) {
    if (sendingRef.current) return;

    if (!restored || !wallet) {
      setNotice({
        tone: "bad",
        text: "Nothing was sent. Connect a mainnet wallet first.",
      });
      return;
    }

    if (!isMainnetChain(wallet.account.chain)) {
      setNotice({
        tone: "bad",
        text: `This wallet is on ${chainLabel(wallet.account.chain)}. Switch it to TON mainnet and connect again. Nothing was sent.`,
      });
      return;
    }

    sendingRef.current = true;
    setSending(true);
    setNotice(null);

    try {
      const response = await tonConnectUI.sendTransaction(request);
      if (!response?.boc) {
        setNotice({ tone: "bad", text: sendFailureMessage("ambiguous") });
        return;
      }
      const first = request.messages[0]?.address ?? "";
      setNotice({
        tone: "good",
        text,
        href: `https://tonviewer.com/${encodeURIComponent(first)}`,
        hrefLabel:
          request.messages.length === 1
            ? "View the destination on Tonviewer"
            : "View the first destination on Tonviewer",
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

  function sendStep(step: ScriptStep) {
    setAttempted((current) => ({ ...current, [step.id]: true }));
    const result = compileScript([step], { fromRaw: wallet?.account.address });
    if (!result.ok || !result.request.messages[0]) {
      setNotice(null);
      return;
    }
    const preview = result.previews[0];
    void transmit(
      result.request,
      `Sent step on mainnet. ${preview?.valueLabel ?? ""} to ${preview?.address ?? ""}.`.trim(),
    );
  }

  function sendScript() {
    setAttempted(Object.fromEntries(steps.map((step) => [step.id, true])));
    const result = compileScript(steps, {
      fromRaw: wallet?.account.address,
      maxMessages: limit?.maxMessages,
    });
    if (!result.ok) {
      setNotice(result.message ? { tone: "bad", text: result.message } : null);
      return;
    }
    const count = result.request.messages.length;
    void transmit(
      result.request,
      `Sent ${count} ${count === 1 ? "message" : "messages"} on mainnet in one confirmation.`,
    );
  }

  const limitCopy = limit
    ? limit.advertised
      ? `This wallet accepts ${limit.maxMessages} ${limit.maxMessages === 1 ? "message" : "messages"} per confirmation.`
      : `This wallet did not advertise a message limit, so a script is capped at ${limit.maxMessages} messages per confirmation.`
    : "Connect a mainnet wallet to send. Its maxMessages decides how many steps fit in one confirmation.";

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
          Script outgoing messages on The Open Network main network. Each step
          is one message. The connected wallet signs and broadcasts it.
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
            <button type="button" className="ton-button" onClick={() => void connect()}>
              Connect wallet
            </button>
          )}
          {connectNotice ? <p className="ton-status">{connectNotice}</p> : null}
        </section>

        <div className="ton-steps">
          {steps.map((step, index) => {
            const result = compiled[index];
            const errors: StepErrors | undefined = result && !result.ok ? result.errors : undefined;
            return (
              <ScriptStepCard
                key={step.id}
                index={index}
                total={steps.length}
                step={step}
                preview={result?.ok ? result.preview : undefined}
                errors={errors}
                showErrors={Boolean(attempted[step.id])}
                sending={sending}
                sendDisabled={
                  sending || !restored || Boolean(wallet && !onMainnet)
                }
                onChange={(next) => updateStep(step.id, next)}
                onMove={(direction) => moveStep(index, direction)}
                onRemove={() => {
                  setSteps((current) => current.filter((item) => item.id !== step.id));
                  setNotice(null);
                }}
                onSend={() => sendStep(step)}
              />
            );
          })}
        </div>

        <div className="ton-script">
          <button
            type="button"
            className="ton-button ton-button-quiet"
            onClick={() =>
              setSteps((current) => [
                ...current,
                emptyStep(`step-${current.length + 1}-${Date.now()}`),
              ])
            }
            disabled={sending}
          >
            Add message
          </button>
          <p className="ton-hint">
            Send script puts every step in one TonConnect confirmation when the
            script fits the wallet limit. Send step always sends that one
            message. Messages in one confirmation are signed together, and each
            destination still runs on its own. {limitCopy}
          </p>
          {overLimit && limit ? (
            <p className="ton-error">
              This wallet accepts {limit.maxMessages}{" "}
              {limit.maxMessages === 1 ? "message" : "messages"} per confirmation.
              This script has {steps.length}.
            </p>
          ) : null}
          <div aria-live="polite">
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
          <button
            type="button"
            className="ton-button"
            onClick={sendScript}
            disabled={
              sending ||
              !restored ||
              steps.length === 0 ||
              overLimit ||
              Boolean(wallet && !onMainnet)
            }
          >
            {sending ? "Waiting for the wallet" : "Send script"}
          </button>
          <p className="ton-hint">Mainnet. Sent messages are final.</p>
        </div>
      </main>
    </div>
  );
}
