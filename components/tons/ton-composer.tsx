"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Address } from "@ton/core";
import {
  useIsConnectionRestored,
  useTonAddress,
  useTonConnectUI,
  useTonWallet,
} from "@tonconnect/ui-react";
import { CopyButton } from "@/components/tons/copy-button";
import { ScriptStepCard } from "@/components/tons/script-step";
import {
  TonProvider,
  clearConnectNotice,
  reportConnectNotice,
  subscribeConnectNotice,
} from "@/components/tons/ton-provider";
import {
  chainLabel,
  classifySendError,
  compileScript,
  compileStep,
  connectFailureMessage,
  isMainnetChain,
  readMaxMessages,
  scriptValueSummary,
  sendFailureMessage,
  type MainnetScriptRequest,
  type ScriptStep,
  type StepErrors,
} from "@/lib/ton-message";
import { utonTemplateBody, utonTemplateById } from "@/lib/uton-templates";
import {
  FUNDED_WALLET_ADDRESS,
  FUNDED_WALLET_MAX_MESSAGES,
} from "@/lib/funded-wallet-public";

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
  const [steps, setSteps] = useState<ScriptStep[]>(() => [stakeDraft("step-1")]);
  const [attempted, setAttempted] = useState<Record<string, boolean>>({});
  const [notice, setNotice] = useState<Notice>(null);
  const [connectNotice, setConnectNotice] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [localWallet, setLocalWallet] = useState(false);

  const onMainnet = isMainnetChain(wallet?.account.chain);
  const fundedRaw = useMemo(
    () => Address.parse(FUNDED_WALLET_ADDRESS).toRawString(),
    [],
  );
  const limit = localWallet
    ? { maxMessages: FUNDED_WALLET_MAX_MESSAGES, advertised: true }
    : readMaxMessages(wallet?.device.features);
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
    if (localWallet) {
      await transmitLocal(request, text);
      return;
    }

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

  async function transmitLocal(request: MainnetScriptRequest, text: string) {
    sendingRef.current = true;
    setSending(true);
    setNotice(null);

    try {
      const response = await fetch("/api/ton/send", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request),
      });
      const payload: unknown = await response.json().catch(() => null);
      if (isFundedOk(payload)) {
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
        return;
      }
      if (isFundedRejected(payload)) {
        setNotice({ tone: "bad", text: payload.message });
        return;
      }
      setNotice({ tone: "bad", text: sendFailureMessage("ambiguous") });
    } catch {
      setNotice({ tone: "bad", text: sendFailureMessage("ambiguous") });
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }

  function sendStep(step: ScriptStep) {
    setAttempted((current) => ({ ...current, [step.id]: true }));
    const result = compileScript([step], {
      fromRaw: localWallet ? fundedRaw : wallet?.account.address,
    });
    if (!result.ok || !result.request.messages[0]) {
      setNotice(null);
      return;
    }
    const preview = result.previews[0];
    void transmit(
      result.request,
      `Sent the stake on mainnet. ${preview?.valueLabel ?? ""} to ${preview?.address ?? ""}.`.trim(),
    );
  }

  function sendScript() {
    setAttempted(Object.fromEntries(steps.map((step) => [step.id, true])));
    const result = compileScript(steps, {
      fromRaw: localWallet ? fundedRaw : wallet?.account.address,
      maxMessages: limit?.maxMessages,
    });
    if (!result.ok) {
      setNotice(result.message ? { tone: "bad", text: result.message } : null);
      return;
    }
    void transmit(result.request, "Sent the stake on mainnet.");
  }

  const limitCopy = limit
    ? limit.advertised
      ? `This wallet accepts ${limit.maxMessages} ${limit.maxMessages === 1 ? "message" : "messages"} per confirmation.`
      : `This wallet did not advertise a message limit, so a script is capped at ${limit.maxMessages} messages per confirmation.`
    : "Connect a mainnet wallet, or use the funded wallet, to send this stake.";

  return (
    <section className="ton-section" id="message" aria-labelledby="ton-message-title">
      <h2 id="ton-message-title">Stake</h2>
      <p className="ton-section-copy">
        The fields are the stake proxy_ton expects. Edit any value. TonConnect
        or the funded wallet signs this one message. Nothing is sent until you
        choose Send stake.
      </p>

      <section className="ton-wallet" aria-live="polite">
        {localWallet ? (
          <div className="ton-wallet-row">
            <div>
              <p className="ton-kicker">Local wallet · mainnet</p>
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
            <button
              type="button"
              className="ton-button ton-button-quiet"
              onClick={() => setLocalWallet(false)}
              disabled={sending}
            >
              Disconnect
            </button>
          </div>
        ) : !restored ? (
          <div>
            <p className="ton-status">Checking for a connected wallet.</p>
            <div className="ton-wallet-actions">
              <button
                type="button"
                className="ton-button ton-button-quiet"
                onClick={() => setLocalWallet(true)}
              >
                Use funded wallet
              </button>
            </div>
          </div>
        ) : wallet && onMainnet ? (
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
                onClick={() => setLocalWallet(true)}
                disabled={sending}
              >
                Use funded wallet
              </button>
              <button
                type="button"
                className="ton-button ton-button-quiet"
                onClick={() => void disconnect()}
                disabled={sending}
              >
                Disconnect
              </button>
            </div>
          </div>
        ) : wallet ? (
          <div className="ton-wallet-row">
            <div>
              <p className="ton-status">
                This wallet is on {chainLabel(wallet.account.chain)}. Switch it
                to TON mainnet and connect again.
              </p>
            </div>
            <div className="ton-wallet-actions">
              <button
                type="button"
                className="ton-button ton-button-quiet"
                onClick={() => setLocalWallet(true)}
              >
                Use funded wallet
              </button>
              <button
                type="button"
                className="ton-button ton-button-quiet"
                onClick={() => void disconnect()}
              >
                Disconnect
              </button>
            </div>
          </div>
        ) : (
          <div>
            <div className="ton-wallet-actions">
              <button type="button" className="ton-button" onClick={() => void connect()}>
                Connect wallet
              </button>
              <button
                type="button"
                className="ton-button ton-button-quiet"
                onClick={() => setLocalWallet(true)}
              >
                Use funded wallet
              </button>
            </div>
            <p className="ton-hint">
              Mainnet only. A testnet wallet is refused. Use funded wallet
              sends from the desk wallet without TonConnect.
            </p>
          </div>
        )}
        {localWallet ? (
          <p className="ton-hint">
            Signs on the server and broadcasts on mainnet. Disconnect to use
            TonConnect instead.
          </p>
        ) : null}
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
                  sending ||
                  (!localWallet && (!restored || Boolean(wallet && !onMainnet)))
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
          <p className="ton-summary-line">{scriptValueSummary(compiled)}</p>
          <p className="ton-hint">{limitCopy}</p>
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
          <div className="ton-actions">
            <button
              type="button"
              className="ton-button"
              onClick={sendScript}
              disabled={
                sending ||
                steps.length === 0 ||
                overLimit ||
                (!localWallet && (!restored || Boolean(wallet && !onMainnet)))
              }
            >
              {sending
                ? localWallet
                  ? "Sending"
                  : "Waiting for the wallet"
                : "Send stake"}
            </button>
          </div>
          <p className="ton-hint">
            Send stake signs this deposit on mainnet. A sent message is final.
          </p>
        </div>
    </section>
  );
}

function isFundedOk(payload: unknown): payload is { ok: true } {
  return Boolean(payload && typeof payload === "object" && "ok" in payload && payload.ok === true);
}

function isFundedRejected(
  payload: unknown,
): payload is { ok: false; kind: "rejected"; message: string } {
  return Boolean(
    payload &&
      typeof payload === "object" &&
      "ok" in payload &&
      payload.ok === false &&
      "kind" in payload &&
      payload.kind === "rejected" &&
      "message" in payload &&
      typeof payload.message === "string",
  );
}

function stakeDraft(id: string): ScriptStep {
  const template = utonTemplateById("stake-ton");
  if (!template) {
    return {
      id,
      destination: "",
      amount: "",
      unit: "ton",
      bounceable: true,
      body: { kind: "empty" },
    };
  }
  const body = utonTemplateBody(template);
  return {
    id,
    destination: "",
    amount: "",
    unit: "ton",
    bounceable: template.bounceable,
    body: {
      ...body,
      fields: body.fields.map((field) =>
        field.id === "user" || field.id === "response"
          ? { ...field, value: FUNDED_WALLET_ADDRESS }
          : field,
      ),
    },
  };
}
