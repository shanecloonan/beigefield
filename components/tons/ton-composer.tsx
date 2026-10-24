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
import { PayoutDesk } from "@/components/tons/payout-desk";
import { ProxyBurnDesk } from "@/components/tons/proxy-burn-desk";
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
  sendFailureMessage,
  type MainnetScriptRequest,
  type ScriptStep,
  type StepErrors,
} from "@/lib/ton-message";
import { utonTemplateBody, utonTemplateById } from "@/lib/uton-templates";
import { utonMinter } from "@/lib/uton";
import {
  FUNDED_WALLET_ADDRESS,
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
  const [steps, setSteps] = useState<ScriptStep[]>(() => [
    stakeDraft("step-1"),
    burnDraft("step-2"),
    notificationDraft("step-3"),
    withdrawDraft("step-5"),
  ]);
  const [pendingAddress, setPendingAddress] = useState("");
  const pendingRef = useRef("");
  const [attempted, setAttempted] = useState<Record<string, boolean>>({});
  const [notice, setNotice] = useState<Notice>(null);
  const [noticeStepId, setNoticeStepId] = useState<string | null>(null);
  const [connectNotice, setConnectNotice] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [localWallet, setLocalWallet] = useState(false);

  const onMainnet = isMainnetChain(wallet?.account.chain);
  const fundedRaw = useMemo(
    () => Address.parse(FUNDED_WALLET_ADDRESS).toRawString(),
    [],
  );
  const compiled = useMemo(() => steps.map((step) => compileStep(step)), [steps]);

  useEffect(() => subscribeConnectNotice(setConnectNotice), []);

  function updatePendingAddress(next: string) {
    const previous = pendingRef.current;
    pendingRef.current = next;
    setPendingAddress(next);
    setSteps((current) =>
      current.map((step) =>
        templateId(step) === "withdraw" && step.destination === previous
          ? { ...step, destination: next }
          : step,
      ),
    );
  }

  function updateStep(id: string, next: ScriptStep) {
    setSteps((current) => current.map((step) => (step.id === id ? next : step)));
    setNotice(null);
    setNoticeStepId(null);
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

  async function transmit(request: MainnetScriptRequest, text: string, stepId: string) {
    if (sendingRef.current) return;
    setNoticeStepId(stepId);
    if (localWallet) {
      await transmitLocal(request, text, stepId);
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
    setSendingId(stepId);
    setSending(true);
    setNotice(null);
    setNoticeStepId(stepId);

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
      setSendingId(null);
    }
  }

  async function transmitLocal(request: MainnetScriptRequest, text: string, stepId: string) {
    sendingRef.current = true;
    setSendingId(stepId);
    setSending(true);
    setNotice(null);
    setNoticeStepId(stepId);

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
      setSendingId(null);
    }
  }

  function sendStep(step: ScriptStep) {
    setAttempted((current) => ({ ...current, [step.id]: true }));
    const result = compileScript([step], {
      fromRaw: localWallet ? fundedRaw : wallet?.account.address,
    });
    if (!result.ok || !result.request.messages[0]) {
      setNoticeStepId(step.id);
      setNotice(null);
      return;
    }
    const preview = result.previews[0];
    void transmit(
      result.request,
      `Sent the ${sentName(step)} on mainnet. ${preview?.valueLabel ?? ""} to ${preview?.address ?? ""}.`.trim(),
      step.id,
    );
  }

  return (
    <section className="ton-section" id="message" aria-labelledby="ton-message-title">
      <h2 id="ton-message-title">Messages</h2>
      <p className="ton-section-copy">
        Step 1 stakes native TON. Step 2 burns uTON. Step 3 is the burn
        notification the jetton wallet sends to the minter. Step 4 is the
        minter and proxy after that notification is accepted. Step 5 is the
        owner withdraw to the pending contract. Step 6 is the query, the ack,
        and the proxy payout after that. Edit any value. TonConnect or the
        funded wallet signs the message you choose. Nothing is sent until you
        press the button on that step.
      </p>
      <nav className="ton-contents" aria-label="Message steps">
        <a href="#stake-form">Step 1 · Stake</a>
        <a href="#burn-form">Step 2 · Burn</a>
        <a href="#notify-form">Step 3 · Burn notification</a>
        <a href="#proxy-burn-form">Step 4 · Proxy burn</a>
        <a href="#withdraw-form">Step 5 · Withdraw</a>
        <a href="#payout-form">Step 6 · Payout</a>
      </nav>

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
            if (templateId(step) === "withdraw") return null;
            const result = compiled[index];
            const errors: StepErrors | undefined = result && !result.ok ? result.errors : undefined;
            return (
              <div key={step.id}>
              <ScriptStepCard
                index={index}
                total={steps.length}
                step={step}
                preview={result?.ok ? result.preview : undefined}
                errors={errors}
                showErrors={Boolean(attempted[step.id])}
                sending={sendingId === step.id}
                sendLabel={
                  sendingId === step.id
                    ? localWallet
                      ? "Sending"
                      : "Waiting for the wallet"
                    : sendLabel(step)
                }
                sendDisabled={
                  sending ||
                  (!localWallet && (!restored || Boolean(wallet && !onMainnet)))
                }
                onChange={(next) => updateStep(step.id, next)}
                onMove={(direction) => moveStep(index, direction)}
                onRemove={() => {
                  setSteps((current) => current.filter((item) => item.id !== step.id));
                  setNotice(null);
                  setNoticeStepId(null);
                }}
                onSend={() => sendStep(step)}
              />
              {notice && noticeStepId === step.id ? (
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
            );
          })}
          <ProxyBurnDesk
            burn={steps.find((step) => templateId(step) === "uton-burn") ?? burnDraft("step-2")}
            notification={
              steps.find((step) => templateId(step) === "burn-notification") ??
              notificationDraft("step-3")
            }
            pendingAddress={pendingAddress}
            onPendingAddress={updatePendingAddress}
          />
          {steps.map((step, index) => {
            if (templateId(step) !== "withdraw") return null;
            const result = compiled[index];
            const errors: StepErrors | undefined = result && !result.ok ? result.errors : undefined;
            return (
              <div key={step.id}>
              <ScriptStepCard
                index={index}
                total={steps.length}
                step={step}
                preview={result?.ok ? result.preview : undefined}
                errors={errors}
                showErrors={Boolean(attempted[step.id])}
                sending={sendingId === step.id}
                sendLabel={
                  sendingId === step.id
                    ? localWallet
                      ? "Sending"
                      : "Waiting for the wallet"
                    : sendLabel(step)
                }
                sendDisabled={
                  sending ||
                  (!localWallet && (!restored || Boolean(wallet && !onMainnet)))
                }
                onChange={(next) => updateStep(step.id, next)}
                onMove={(direction) => moveStep(index, direction)}
                onRemove={() => {
                  setSteps((current) => current.filter((item) => item.id !== step.id));
                  setNotice(null);
                  setNoticeStepId(null);
                }}
                onSend={() => sendStep(step)}
              />
              {notice && noticeStepId === step.id ? (
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
            );
          })}
          <PayoutDesk
            pendingAddress={pendingAddress}
            withdraw={steps.find((step) => templateId(step) === "withdraw") ?? withdrawDraft("step-5")}
          />
        </div>

        <p className="ton-hint">
          Each send button sends only that message. Mainnet. A sent message is
          final. Send on steps 4 and 6 is locked.
        </p>
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

function templateId(step: ScriptStep): string | undefined {
  return step.body.kind === "fields" ? step.body.templateId : undefined;
}

function sendLabel(step: ScriptStep): string {
  const id = step.body.kind === "fields" ? step.body.templateId : undefined;
  if (id === "uton-burn") return "Send burn";
  if (id === "burn-notification") return "Send burn notification";
  if (id === "withdraw") return "Send withdraw";
  return "Send stake";
}

function sentName(step: ScriptStep): string {
  const id = step.body.kind === "fields" ? step.body.templateId : undefined;
  if (id === "uton-burn") return "burn";
  if (id === "burn-notification") return "burn notification";
  if (id === "withdraw") return "withdraw";
  return "stake";
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

function burnDraft(id: string): ScriptStep {
  const template = utonTemplateById("uton-burn");
  if (!template) return stakeDraft(id);
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
        field.id === "response" ? { ...field, value: FUNDED_WALLET_ADDRESS } : field,
      ),
    },
  };
}

function withdrawDraft(id: string): ScriptStep {
  const template = utonTemplateById("withdraw");
  if (!template) return stakeDraft(id);
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
        field.id === "recipient" || field.id === "response"
          ? { ...field, value: FUNDED_WALLET_ADDRESS }
          : field,
      ),
    },
  };
}

function notificationDraft(id: string): ScriptStep {
  const template = utonTemplateById("burn-notification");
  if (!template) return burnDraft(id);
  const body = utonTemplateBody(template);
  return {
    id,
    destination: utonMinter,
    amount: "",
    unit: "ton",
    bounceable: template.bounceable,
    body: {
      ...body,
      fields: body.fields.map((field) =>
        field.id === "owner" || field.id === "response"
          ? { ...field, value: FUNDED_WALLET_ADDRESS }
          : field,
      ),
    },
  };
}
