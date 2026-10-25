"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Address } from "@ton/core";
import {
  useIsConnectionRestored,
  useTonAddress,
  useTonConnectUI,
  useTonWallet,
} from "@tonconnect/ui-react";
import { AutomationGap } from "@/components/tons/automation-gap";
import { BounceDesk, type BounceNotice } from "@/components/tons/bounce-desk";
import { PayoutDesk } from "@/components/tons/payout-desk";
import { ScriptStepCard, type StepPlace } from "@/components/tons/script-step";
import {
  TonProvider,
  clearConnectNotice,
  reportConnectNotice,
  subscribeConnectNotice,
} from "@/components/tons/ton-provider";
import {
  TonsWalletDesk,
  tonsInFlightLabel,
  tonsStepSendDisabled,
} from "@/components/tons/wallet-desk";
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
import { automationSource } from "@/lib/uton-automation";
import { pathSource } from "@/lib/uton-path";
import { utonTemplateBody, utonTemplateById } from "@/lib/uton-templates";
import { utonMinter } from "@/lib/uton";
import { FUNDED_WALLET_ADDRESS } from "@/lib/funded-wallet-public";

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
    burnDraft("burn"),
    notificationDraft("notify"),
    redeemBurnDraft("redeem-burn"),
    redeemNotificationDraft("redeem-notify"),
    withdrawDraft("withdraw"),
  ]);
  const [attempted, setAttempted] = useState<Record<string, boolean>>({});
  const [notice, setNotice] = useState<BounceNotice | null>(null);
  const [noticeStepId, setNoticeStepId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [connectNotice, setConnectNotice] = useState<string | null>(null);
  const [localWallet, setLocalWallet] = useState(false);

  const onMainnet = isMainnetChain(wallet?.account.chain);
  const fundedRaw = useMemo(
    () => Address.parse(FUNDED_WALLET_ADDRESS).toRawString(),
    [],
  );
  const compiled = useMemo(() => steps.map((step) => compileStep(step)), [steps]);

  useEffect(() => subscribeConnectNotice(setConnectNotice), []);

  function updateStep(id: string, next: ScriptStep) {
    setSteps((current) => current.map((step) => (step.id === id ? next : step)));
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
    if (localWallet) {
      await transmitLocal(request, text, stepId);
      return;
    }
    setNoticeStepId(stepId);

    if (!wallet) {
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
          hrefLabel: "View the destination on Tonviewer",
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
    setNoticeStepId(step.id);
    if (!result.ok || !result.request.messages[0]) {
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

function sendBounce() {
  const step = steps.find((item) => item.id === "notify") ?? notificationDraft("notify");
  setAttempted((current) => ({ ...current, [step.id]: true }));
  const result = compileScript([step], {
    fromRaw: localWallet ? fundedRaw : wallet?.account.address,
  });
  setNoticeStepId("bounce");
  if (!result.ok || !result.request.messages[0]) {
    setNotice({
      tone: "bad",
      text: "Nothing was sent. Complete the burn notification, then try again.",
    });
    return;
  }
  const preview = result.previews[0];
  void transmit(
    result.request,
    `Sent the burn notification on mainnet. ${preview?.valueLabel ?? ""} to ${preview?.address ?? ""}.`.trim(),
    "bounce",
  );
}

function resultFor(id: string) {
    const index = steps.findIndex((step) => step.id === id);
    return compiled[index];
  }

  const burn = steps.find((step) => step.id === "burn") ?? burnDraft("burn");
  const notification = steps.find((step) => step.id === "notify") ?? notificationDraft("notify");
  const redeemBurn =
    steps.find((step) => step.id === "redeem-burn") ?? redeemBurnDraft("redeem-burn");
  const redeemNotify =
    steps.find((step) => step.id === "redeem-notify") ?? redeemNotificationDraft("redeem-notify");
  const withdraw = steps.find((step) => step.id === "withdraw") ?? withdrawDraft("withdraw");

  function renderStep(step: ScriptStep, index: number, place: StepPlace) {
    return (
      <LockedStep
        key={step.id}
        step={step}
        index={index}
        total={steps.length}
        result={resultFor(step.id)}
        place={place}
        onChange={(next) => updateStep(step.id, next)}
        sending={sendingId === step.id}
        sendDisabled={tonsStepSendDisabled({
          sending,
          localWallet,
          restored,
          walletOnWrongChain: Boolean(wallet && !onMainnet),
        })}
        localWallet={localWallet}
        showErrors={Boolean(attempted[step.id])}
        notice={noticeStepId === step.id ? notice : null}
        onSend={() => sendStep(step)}
      />
    );
  }

  return (
    <section className="ton-section" id="message" aria-labelledby="ton-message-title">
      <h2 id="ton-message-title">Path</h2>
      <nav className="ton-contents" aria-label="Message steps">
        <a href="#burn-form">Step 1 · Burn</a>
        <a href="#after-burn-1">After step 1 · afterBurn1</a>
        <a href="#notify-form">Step 2 · Notification</a>
        <a href="#bounce-form">Step 3 · on_bounce</a>
        <a href="#queue-after-bounce">After step 3 · nextAfter</a>
        <a href="#redeem-form">Step 4 · Redeem burn</a>
        <a href="#redeem-notify-form">Step 5 · Redeem notification</a>
        <a href="#withdraw-form">Step 6 · Withdraw</a>
        <a href="#payout-form">Payout</a>
      </nav>

      <TonsWalletDesk
        localWallet={localWallet}
        restored={restored}
        connected={Boolean(wallet)}
        onMainnet={onMainnet}
        address={address}
        chainName={wallet ? chainLabel(wallet.account.chain) : ""}
        sending={sending}
        connectNotice={connectNotice}
        fundedAddress={FUNDED_WALLET_ADDRESS}
        onUseFunded={() => setLocalWallet(true)}
        onClearFunded={() => setLocalWallet(false)}
        onConnect={() => void connect()}
        onDisconnect={() => void disconnect()}
      />

      <div className="ton-steps">
        {renderStep(burn, 0, burnPlace)}
        <AutomationGap
          id="after-burn-1"
          titleId="after-burn-1-title"
          kicker="After step 1"
          title="afterBurn1"
          sources={[automationSource.afterBurn1]}
          detail="Nothing was sent. afterBurn1 watches the path. It is not a wallet message."
        />
        {renderStep(notification, 1, notifyPlace)}
        <BounceDesk
          sending={sendingId === "bounce"}
          sendLabel={sendingId === "bounce" ? tonsInFlightLabel(localWallet) : "Send"}
          disabled={tonsStepSendDisabled({
            sending,
            localWallet,
            restored,
            walletOnWrongChain: Boolean(wallet && !onMainnet),
          })}
          notice={noticeStepId === "bounce" ? notice : null}
          onSend={sendBounce}
        />
        <AutomationGap
          id="queue-after-bounce"
          titleId="queue-after-bounce-title"
          kicker="After step 3"
          title="nextAfter"
          sources={[automationSource.queueAfterBounce]}
          detail="Nothing was sent. nextAfter names the steps after the bounce. It is not a wallet message."
        />
        {renderStep(redeemBurn, 2, redeemBurnPlace)}
        {renderStep(redeemNotify, 3, redeemNotifyPlace)}
        {renderStep(withdraw, 4, withdrawPlace)}
        <PayoutDesk />
      </div>
    </section>
  );
}

function LockedStep({
  step,
  index,
  total,
  result,
  place,
  onChange,
  sending,
  sendDisabled,
  localWallet,
  showErrors,
  notice,
  onSend,
}: {
  step: ScriptStep;
  index: number;
  total: number;
  result: ReturnType<typeof compileStep> | undefined;
  place: StepPlace;
  onChange: (step: ScriptStep) => void;
  sending: boolean;
  sendDisabled: boolean;
  localWallet: boolean;
  showErrors: boolean;
  notice: Notice;
  onSend: () => void;
}) {
  const errors: StepErrors | undefined = result && !result.ok ? result.errors : undefined;
  return (
    <ScriptStepCard
      index={index}
      total={total}
      step={step}
      preview={result?.ok ? result.preview : undefined}
      errors={errors}
      showErrors={showErrors}
      sending={sending}
      sendLabel={sending ? tonsInFlightLabel(localWallet) : sendLabel(step)}
      sendDisabled={sendDisabled}
      place={place}
      status={<StepNotice notice={notice} />}
      onChange={onChange}
      onMove={() => undefined}
      onRemove={() => undefined}
      onSend={onSend}
    />
  );
}

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

function StepNotice({ notice }: { notice: Notice }) {
  if (!notice) return null;
  return (
    <p className={notice.tone === "good" ? "ton-good" : "ton-error"} role="status">
      {notice.text}{" "}
      {notice.tone === "good" ? (
        <a href={notice.href} target="_blank" rel="noreferrer">
          {notice.hrefLabel}
        </a>
      ) : null}
    </p>
  );
}

const burnPlace: StepPlace = {
  anchor: "burn-form",
  kicker: "Step 1 · Proxy id 3",
  title: "burn_tokens",
  sources: [pathSource.burnTokens],
};

const notifyPlace: StepPlace = {
  anchor: "notify-form",
  kicker: "Step 2 · Proxy id 3",
  title: "proxy_burn",
  sources: [pathSource.minterRecv, pathSource.proxyBurn],
};

const redeemBurnPlace: StepPlace = {
  anchor: "redeem-form",
  kicker: "Step 4 · Whitelisted proxy",
  title: "burn_tokens",
  sources: [pathSource.burnTokens],
};

const redeemNotifyPlace: StepPlace = {
  anchor: "redeem-notify-form",
  kicker: "Step 5 · Whitelisted proxy",
  title: "burn",
  sources: [pathSource.proxyTonBurn],
};

const withdrawPlace: StepPlace = {
  anchor: "withdraw-form",
  kicker: "Step 6 · After the time lock",
  title: "withdraw_ton",
  sources: [pathSource.withdrawTon],
};

function templateId(step: ScriptStep): string | undefined {
  return step.body.kind === "fields" ? step.body.templateId : undefined;
}

function sendLabel(step: ScriptStep): string {
  if (step.id === "redeem-burn") return "Send redeem burn";
  if (step.id === "redeem-notify") return "Send redeem notification";
  const id = templateId(step);
  if (id === "uton-burn") return "Send burn";
  if (id === "burn-notification") return "Send burn notification";
  if (id === "withdraw") return "Send withdraw";
  return "Send";
}

function sentName(step: ScriptStep): string {
  if (step.id === "redeem-burn") return "redeem burn";
  if (step.id === "redeem-notify") return "redeem notification";
  const id = templateId(step);
  if (id === "uton-burn") return "burn";
  if (id === "burn-notification") return "burn notification";
  if (id === "withdraw") return "withdraw";
  return "message";
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

function emptyDraft(id: string): ScriptStep {
  return {
    id,
    destination: "",
    amount: "",
    unit: "ton",
    bounceable: true,
    body: { kind: "empty" },
  };
}

function withProxy(step: ScriptStep, proxy: string): ScriptStep {
  if (step.body.kind !== "fields") return step;
  return {
    ...step,
    body: {
      ...step.body,
      fields: step.body.fields.map((field) =>
        field.id === "proxy_id" ? { ...field, value: proxy } : field,
      ),
    },
  };
}

function burnDraft(id: string): ScriptStep {
  const template = utonTemplateById("uton-burn");
  if (!template) return emptyDraft(id);
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

function redeemBurnDraft(id: string): ScriptStep {
  return withProxy(burnDraft(id), "");
}

function withdrawDraft(id: string): ScriptStep {
  const template = utonTemplateById("withdraw");
  if (!template) return emptyDraft(id);
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

function redeemNotificationDraft(id: string): ScriptStep {
  return withProxy(notificationDraft(id), "");
}
