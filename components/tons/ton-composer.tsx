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
import { PathRunBar } from "@/components/tons/path-run-bar";
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
  outgoingRequest,
  isMainnetChain,
  readFundedSendResult,
  readMaxMessages,
  sendFailureMessage,
  type MainnetScriptRequest,
  type ScriptStep,
  type StepErrors,
} from "@/lib/ton-message";
import {
  afterBurn1,
  afterBurn1Trace,
  automationSource,
  laterDraftId,
  nextAfter,
} from "@/lib/uton-automation";
import { pathSource } from "@/lib/uton-path";
import { compileMinterQuery, minterQueryFailure } from "@/lib/uton-query";
import {
  applyPathDefaults,
  compilePathRun,
  pathOwner,
  PATH_GAS_TON,
  PATH_UTON_NANO,
} from "@/lib/uton-path-run";
import { utonTemplateBody, utonTemplateById } from "@/lib/uton-templates";
import { utonMinter } from "@/lib/uton";
import { FUNDED_WALLET_ADDRESS, FUNDED_WALLET_MAX_MESSAGES } from "@/lib/funded-wallet-public";

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
  const [pathPart, setPathPart] = useState<string | null>(null);
  const [lookupNote, setLookupNote] = useState<string | null>(null);
  const ownerRef = useRef("");
  const jettonRef = useRef("");
  const proxyRef = useRef<string | undefined>(undefined);
  const stepsRef = useRef(steps);
  stepsRef.current = steps;

  const onMainnet = isMainnetChain(wallet?.account.chain);
  const messageLimit = localWallet
    ? FUNDED_WALLET_MAX_MESSAGES
    : readMaxMessages(wallet?.device.features)?.maxMessages;
  const fundedRaw = useMemo(
    () => Address.parse(FUNDED_WALLET_ADDRESS).toRawString(),
    [],
  );
  const compiled = useMemo(() => steps.map((step) => compileStep(step)), [steps]);

  useEffect(() => subscribeConnectNotice(setConnectNotice), []);

  useEffect(() => {
    const owner = pathOwner({ localWallet, onMainnet, address });
    let cancel = false;
    void (async () => {
      const defaults = await fetchPathDefaults(owner);
      if (cancel || !defaults) return;
      if (!defaults.ok) {
        setLookupNote(defaults.message);
        return;
      }
      setLookupNote(null);
      setNotice((current) => (current && stalePathNotice(current.text) ? null : current));
      setSteps((current) =>
        applyPathDefaults(current, {
          owner,
          jettonWallet: defaults.jettonWallet,
          proxyId: defaults.proxyId,
          previousOwner: ownerRef.current,
          previousJetton: jettonRef.current,
          previousProxy: proxyRef.current,
        }),
      );
      ownerRef.current = owner;
      jettonRef.current = defaults.jettonWallet;
      proxyRef.current = defaults.proxyId;
    })();
    return () => {
      cancel = true;
    };
  }, [localWallet, address, onMainnet]);

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

  function guardWallet(stepId: string): boolean {
    setNoticeStepId(stepId);
    if (localWallet) return true;
    if (!wallet) {
      setNotice({
        tone: "bad",
        text: "Nothing was sent. Connect a mainnet wallet first.",
      });
      return false;
    }
    if (!isMainnetChain(wallet.account.chain)) {
      setNotice({
        tone: "bad",
        text: `This wallet is on ${chainLabel(wallet.account.chain)}. Switch it to TON mainnet and connect again. Nothing was sent.`,
      });
      return false;
    }
    return true;
  }

  async function deliver(
    request: MainnetScriptRequest,
  ): Promise<{ ok: true } | { ok: false; text: string }> {
    if (localWallet) {
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
    try {
      const response = await tonConnectUI.sendTransaction(request);
      if (!response?.boc) return { ok: false, text: sendFailureMessage("ambiguous") };
      return { ok: true };
    } catch (error) {
      return { ok: false, text: sendFailureMessage(classifySendError(error)) };
    }
  }

  async function transmit(request: MainnetScriptRequest, text: string, stepId: string) {
    if (sendingRef.current) return false;
    if (!guardWallet(stepId)) return false;
    sendingRef.current = true;
    setSendingId(stepId);
    setSending(true);
    setNotice(null);
    try {
      const result = await deliver(request);
      if (!result.ok) {
        setNotice({ tone: "bad", text: result.text });
        return false;
      }
      const first = request.messages[0]?.address ?? "";
      setNotice({
        tone: "good",
        text,
        href: `https://tonviewer.com/${encodeURIComponent(first)}`,
        hrefLabel: "View the destination on Tonviewer",
      });
      return true;
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

  function sendDrafts(
    ids: readonly string[],
    stepId: string,
    sentName: string,
    incomplete: string,
  ) {
    setAttempted((current) => {
      const next = { ...current };
      for (const id of ids) next[id] = true;
      return next;
    });
    if (ids.length === 0) {
      setNoticeStepId(stepId);
      setNotice({ tone: "bad", text: incomplete });
      return;
    }
    const selected: ScriptStep[] = [];
    for (const id of ids) {
      const step = steps.find((item) => item.id === id);
      if (!step) {
        setNoticeStepId(stepId);
        setNotice({ tone: "bad", text: incomplete });
        return;
      }
      selected.push(step);
    }
    const result = compileScript(selected, {
      fromRaw: localWallet ? fundedRaw : wallet?.account.address,
      maxMessages: messageLimit,
    });
    setNoticeStepId(stepId);
    if (!result.ok) {
      const broken = result.steps.some((item) => item && Object.keys(item).length > 0);
      setNotice({
        tone: "bad",
        text: !broken && result.message ? result.message : incomplete,
      });
      return;
    }
    const preview = result.previews[0];
    const text =
      result.previews.length > 1
        ? `Sent the queued path on mainnet. ${result.previews.length} messages. First is ${preview?.valueLabel ?? ""} to ${preview?.address ?? ""}.`.trim()
        : `Sent the ${sentName} on mainnet. ${preview?.valueLabel ?? ""} to ${preview?.address ?? ""}.`.trim();
    void transmit(result.request, text, stepId);
  }

  function sendAfterBurn1() {
    const ids = afterBurn1(afterBurn1Trace).map(laterDraftId);
    sendDrafts(
      ids,
      "after-burn-1",
      "queued path",
      "Nothing was sent. Complete the redeem burn, the redeem notification, and the withdraw, then try again.",
    );
  }

  function sendNextAfter() {
    const next = nextAfter("bounce");
    if (!next) {
      setNoticeStepId("queue-after-bounce");
      setNotice({
        tone: "bad",
        text: "Nothing was sent. Complete the redeem burn, then try again.",
      });
      return;
    }
    sendDrafts(
      [laterDraftId(next)],
      "queue-after-bounce",
      "redeem burn",
      "Nothing was sent. Complete the redeem burn, then try again.",
    );
  }

  function sendQuery() {
    const step = steps.find((item) => item.id === "withdraw") ?? withdrawDraft("withdraw");
    setAttempted((current) => ({ ...current, [step.id]: true }));
    const compiled = compileMinterQuery(step);
    setNoticeStepId("payout");
    if (!compiled.ok) {
      setNotice({ tone: "bad", text: minterQueryFailure(compiled.errors) });
      return;
    }
    const preview = compiled.preview;
    void transmit(
      outgoingRequest([compiled.message], {
        fromRaw: localWallet ? fundedRaw : wallet?.account.address,
      }),
      `Sent the minter query on mainnet. ${preview.valueLabel} to ${preview.address}. The minter answers this sender with query_ack.`,
      "payout",
    );
  }

  async function runPath() {
    if (sendingRef.current) return;
    if (!guardWallet("path")) return;
    sendingRef.current = true;
    setSending(true);
    setSendingId("path");
    setNotice(null);
    setPathPart(null);
    try {
      const owner = pathOwner({ localWallet, onMainnet, address });
      let current = stepsRef.current;
      if (owner) {
        const defaults = await fetchPathDefaults(owner);
        if (defaults?.ok) {
          current = applyPathDefaults(current, {
            owner,
            jettonWallet: defaults.jettonWallet,
            proxyId: defaults.proxyId,
            previousOwner: ownerRef.current,
            previousJetton: jettonRef.current,
            previousProxy: proxyRef.current,
          });
          setSteps(current);
          ownerRef.current = owner;
          jettonRef.current = defaults.jettonWallet;
          proxyRef.current = defaults.proxyId;
          setLookupNote(null);
        } else if (defaults && !defaults.ok) {
          setLookupNote(defaults.message);
        }
      }
      const compiled = compilePathRun(
        {
          burn: current.find((step) => step.id === "burn") ?? burnDraft("burn"),
          notify: current.find((step) => step.id === "notify") ?? notificationDraft("notify"),
          redeemBurn: current.find((step) => step.id === "redeem-burn") ?? redeemBurnDraft("redeem-burn"),
          redeemNotify:
            current.find((step) => step.id === "redeem-notify") ?? redeemNotificationDraft("redeem-notify"),
          withdraw: current.find((step) => step.id === "withdraw") ?? withdrawDraft("withdraw"),
        },
        {
          fromRaw: localWallet ? fundedRaw : wallet?.account.address,
          maxMessages: messageLimit ?? FUNDED_WALLET_MAX_MESSAGES,
        },
      );
      if (!compiled.ok) {
        setNotice({ tone: "bad", text: compiled.message });
        return;
      }
      for (let index = 0; index < compiled.batches.length; index += 1) {
        const batch = compiled.batches[index];
        if (!batch) continue;
        if (compiled.batches.length > 1) {
          setPathPart(`Sending ${index + 1} of ${compiled.batches.length}`);
        }
        const result = await deliver(batch);
        if (!result.ok) {
          const lead =
            index > 0 ? "The first part of the path was sent. The rest was not. " : "";
          setNotice({ tone: "bad", text: `${lead}${result.text}` });
          return;
        }
        if (index < compiled.batches.length - 1 && localWallet) {
          await new Promise((resolve) => setTimeout(resolve, 5000));
        }
      }
      setNotice({
        tone: "good",
        text: [compiled.summary, ...compiled.skipped].join(" "),
        href: `https://tonviewer.com/${encodeURIComponent(compiled.firstAddress)}`,
        hrefLabel: "View the destination on Tonviewer",
      });
    } finally {
      sendingRef.current = false;
      setSending(false);
      setSendingId(null);
      setPathPart(null);
    }
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
  const pathSendDisabled = tonsStepSendDisabled({
    sending,
    localWallet,
    restored,
    walletOnWrongChain: Boolean(wallet && !onMainnet),
  });

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
        sendDisabled={pathSendDisabled}
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
        <a href="#path-run">Run path</a>
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

      <PathRunBar
        sending={sendingId === "path"}
        label={
          sendingId === "path" ? (pathPart ?? tonsInFlightLabel(localWallet)) : "Run path"
        }
        disabled={pathSendDisabled}
        notice={noticeStepId === "path" ? notice : null}
        lookupNote={lookupNote}
        onRun={() => void runPath()}
      />

      <div className="ton-steps">
        {renderStep(burn, 0, burnPlace)}
        <AutomationGap
          id="after-burn-1"
          titleId="after-burn-1-title"
          kicker="After step 1"
          title="afterBurn1"
          sources={[automationSource.afterBurn1]}
          hint="afterBurn1 queues the redeem burn, the redeem notification, and the withdraw once bounce is on the path. Send broadcasts those three messages on mainnet. A sent message is final."
          sending={sendingId === "after-burn-1"}
          sendLabel={sendingId === "after-burn-1" ? tonsInFlightLabel(localWallet) : "Send"}
          disabled={pathSendDisabled}
          notice={noticeStepId === "after-burn-1" ? notice : null}
          onSend={sendAfterBurn1}
        />
        {renderStep(notification, 1, notifyPlace)}
        <BounceDesk
          sending={sendingId === "bounce"}
          sendLabel={sendingId === "bounce" ? tonsInFlightLabel(localWallet) : "Send"}
          disabled={pathSendDisabled}
          notice={noticeStepId === "bounce" ? notice : null}
          onSend={sendBounce}
        />
        <AutomationGap
          id="queue-after-bounce"
          titleId="queue-after-bounce-title"
          kicker="After step 3"
          title="nextAfter"
          sources={[automationSource.queueAfterBounce]}
          hint="nextAfter names the redeem burn after the bounce. Send broadcasts that burn on mainnet. A sent message is final."
          sending={sendingId === "queue-after-bounce"}
          sendLabel={sendingId === "queue-after-bounce" ? tonsInFlightLabel(localWallet) : "Send"}
          disabled={pathSendDisabled}
          notice={noticeStepId === "queue-after-bounce" ? notice : null}
          onSend={sendNextAfter}
        />
        {renderStep(redeemBurn, 2, redeemBurnPlace)}
        {renderStep(redeemNotify, 3, redeemNotifyPlace)}
        {renderStep(withdraw, 4, withdrawPlace)}
        <PayoutDesk
          sending={sendingId === "payout"}
          sendLabel={sendingId === "payout" ? tonsInFlightLabel(localWallet) : "Send"}
          disabled={pathSendDisabled}
          notice={noticeStepId === "payout" ? notice : null}
          onSend={sendQuery}
        />
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
  // Path order is the protocol order. Moving or removing a card would broadcast a different message.
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

const minterNote = `The uTON minter, ${utonMinter}. Filled for you. It is not the jetton wallet.`;

const jettonNote = `This address holds your uTON. ${utonMinter} is the minter, and it is filled on the notification steps. This field is a different address. The minter calculates it from the wallet that sends, starting with the funded desk wallet. You do not paste it.`;

const burnPlace: StepPlace = {
  anchor: "burn-form",
  kicker: "Step 1 · Proxy id 3",
  title: "burn_tokens",
  sources: [pathSource.burnTokens],
  destinationNote: jettonNote,
  amountNote:
    "TON attached pays gas. It starts at 0.2 TON. How many uTON to burn is the amount field below.",
};

const notifyPlace: StepPlace = {
  anchor: "notify-form",
  kicker: "Step 2 · Proxy id 3",
  title: "proxy_burn",
  sources: [pathSource.minterRecv, pathSource.proxyBurn],
  destinationNote: minterNote,
  amountNote: "TON attached pays the minter. It starts at 0.15 TON.",
};

const redeemBurnPlace: StepPlace = {
  anchor: "redeem-form",
  kicker: "Step 4 · Whitelisted proxy",
  title: "burn_tokens",
  sources: [pathSource.burnTokens],
  destinationNote: jettonNote,
  amountNote:
    "TON attached pays gas. It starts at 0.2 TON. The uTON amount starts at 1 uTON and is burned again here, on the listed proxy.",
};

const redeemNotifyPlace: StepPlace = {
  anchor: "redeem-notify-form",
  kicker: "Step 5 · Whitelisted proxy",
  title: "burn",
  sources: [pathSource.proxyTonBurn],
  destinationNote: minterNote,
  amountNote: "TON attached pays the minter. It starts at 0.15 TON.",
};

const withdrawPlace: StepPlace = {
  anchor: "withdraw-form",
  kicker: "Step 6 · After the time lock",
  title: "withdraw_ton",
  sources: [pathSource.withdrawTon],
  destinationNote:
    "The pending withdraw contract is created when a listed proxy accepts a burn. It is not your jetton wallet. It then waits out the proxy's time lock. Paste that contract here after it exists. Run path sends the burns, the notifications, and the minter query without this step until then.",
  amountNote:
    "TON attached pays gas. It starts at 0.5 TON. The TON you receive is paid by the proxy, not by this amount.",
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

function stalePathNotice(text: string): boolean {
  return (
    text.startsWith("Nothing was sent. Connect a mainnet wallet") ||
    text.includes("uTON jetton wallet is still empty")
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
    amount: PATH_GAS_TON.burn,
    unit: "ton",
    bounceable: template.bounceable,
    body: {
      ...body,
      fields: body.fields.map((field) => {
        if (field.id === "response") return { ...field, value: FUNDED_WALLET_ADDRESS };
        if (field.id === "amount") return { ...field, value: PATH_UTON_NANO };
        return field;
      }),
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
    amount: PATH_GAS_TON.withdraw,
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
    amount: PATH_GAS_TON.notify,
    unit: "ton",
    bounceable: template.bounceable,
    body: {
      ...body,
      fields: body.fields.map((field) => {
        if (field.id === "owner" || field.id === "response") {
          return { ...field, value: FUNDED_WALLET_ADDRESS };
        }
        if (field.id === "amount") return { ...field, value: PATH_UTON_NANO };
        return field;
      }),
    },
  };
}

function redeemNotificationDraft(id: string): ScriptStep {
  return withProxy(notificationDraft(id), "");
}

type PathDefaultsPayload =
  | { ok: true; jettonWallet: string; proxyId?: string }
  | { ok: false; message: string };

async function fetchPathDefaults(owner: string): Promise<PathDefaultsPayload | null> {
  try {
    const response = await fetch(`/api/ton/path-defaults?owner=${encodeURIComponent(owner)}`);
    const payload: unknown = await response.json();
    if (!payload || typeof payload !== "object" || !("ok" in payload)) return null;
    if (payload.ok === true && "jettonWallet" in payload && typeof payload.jettonWallet === "string") {
      const proxyId = "proxyId" in payload && typeof payload.proxyId === "string" ? payload.proxyId : undefined;
      return { ok: true, jettonWallet: payload.jettonWallet, proxyId };
    }
    if (payload.ok === false && "message" in payload && typeof payload.message === "string") {
      return { ok: false, message: payload.message };
    }
    return null;
  } catch {
    return null;
  }
}
