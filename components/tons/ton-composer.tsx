"use client";

import { useEffect, useMemo, useState } from "react";
import {
  useIsConnectionRestored,
  useTonAddress,
  useTonConnectUI,
  useTonWallet,
} from "@tonconnect/ui-react";
import { BounceDesk } from "@/components/tons/bounce-desk";
import { CopyButton } from "@/components/tons/copy-button";
import { PayoutDesk } from "@/components/tons/payout-desk";
import { ScriptStepCard, type StepPlace } from "@/components/tons/script-step";
import {
  TonProvider,
  clearConnectNotice,
  reportConnectNotice,
  subscribeConnectNotice,
} from "@/components/tons/ton-provider";
import {
  chainLabel,
  classifySendError,
  compileStep,
  connectFailureMessage,
  isMainnetChain,
  type ScriptStep,
  type StepErrors,
} from "@/lib/ton-message";
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
  const [steps, setSteps] = useState<ScriptStep[]>(() => [
    burnDraft("burn"),
    notificationDraft("notify"),
    redeemBurnDraft("redeem-burn"),
    redeemNotificationDraft("redeem-notify"),
    withdrawDraft("withdraw"),
  ]);
  const [connectNotice, setConnectNotice] = useState<string | null>(null);

  const onMainnet = isMainnetChain(wallet?.account.chain);
  const compiled = useMemo(() => steps.map((step) => compileStep(step)), [steps]);

  useEffect(() => subscribeConnectNotice(setConnectNotice), []);

  function updateStep(id: string, next: ScriptStep) {
    setSteps((current) => current.map((step) => (step.id === id ? next : step)));
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

  function resultFor(id: string) {
    const index = steps.findIndex((step) => step.id === id);
    return compiled[index];
  }

  const burn = steps.find((step) => step.id === "burn") ?? burnDraft("burn");
  const notification = steps.find((step) => step.id === "notify") ?? notificationDraft("notify");
  const withdraw = steps.find((step) => step.id === "withdraw") ?? withdrawDraft("withdraw");

  return (
    <section className="ton-section" id="message" aria-labelledby="ton-message-title">
      <h2 id="ton-message-title">Path</h2>
      <nav className="ton-contents" aria-label="Message steps">
        <a href="#burn-form">Step 1 · Burn</a>
        <a href="#notify-form">Step 2 · Notification</a>
        <a href="#bounce-form">Step 3 · on_bounce</a>
        <a href="#redeem-form">Step 4 · Redeem burn</a>
        <a href="#redeem-notify-form">Step 5 · Redeem notification</a>
        <a href="#withdraw-form">Step 6 · Withdraw</a>
        <a href="#payout-form">Payout</a>
      </nav>

      <section className="ton-wallet" aria-live="polite">
        {!restored ? (
          <div>
            <p className="ton-status">Checking for a connected wallet.</p>
            <div className="ton-wallet-actions">
              <LockedWalletButton />
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
              <LockedWalletButton />
              <button type="button" className="ton-button ton-button-quiet" onClick={() => void disconnect()}>
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
              <LockedWalletButton />
              <button type="button" className="ton-button ton-button-quiet" onClick={() => void disconnect()}>
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
              <LockedWalletButton />
            </div>
          </div>
        )}
        {connectNotice ? <p className="ton-status">{connectNotice}</p> : null}
      </section>

      <div className="ton-steps">
        <LockedStep
          step={burn}
          index={0}
          total={steps.length}
          result={resultFor("burn")}
          place={burnPlace}
          onChange={(next) => updateStep("burn", next)}
        />
        <LockedStep
          step={notification}
          index={1}
          total={steps.length}
          result={resultFor("notify")}
          place={notifyPlace}
          onChange={(next) => updateStep("notify", next)}
        />
        <BounceDesk />
        <LockedStep
          step={steps.find((step) => step.id === "redeem-burn") ?? redeemBurnDraft("redeem-burn")}
          index={2}
          total={steps.length}
          result={resultFor("redeem-burn")}
          place={redeemBurnPlace}
          onChange={(next) => updateStep("redeem-burn", next)}
        />
        <LockedStep
          step={steps.find((step) => step.id === "redeem-notify") ?? redeemNotificationDraft("redeem-notify")}
          index={3}
          total={steps.length}
          result={resultFor("redeem-notify")}
          place={redeemNotifyPlace}
          onChange={(next) => updateStep("redeem-notify", next)}
        />
        <LockedStep
          step={withdraw}
          index={4}
          total={steps.length}
          result={resultFor("withdraw")}
          place={withdrawPlace}
          onChange={(next) => updateStep("withdraw", next)}
        />
        <PayoutDesk />
      </div>
    </section>
  );
}

function LockedWalletButton() {
  return (
    <button type="button" className="ton-button ton-button-quiet" disabled aria-disabled="true">
      Use funded wallet
    </button>
  );
}

function LockedStep({
  step,
  index,
  total,
  result,
  place,
  onChange,
}: {
  step: ScriptStep;
  index: number;
  total: number;
  result: ReturnType<typeof compileStep> | undefined;
  place: StepPlace;
  onChange: (step: ScriptStep) => void;
}) {
  const errors: StepErrors | undefined = result && !result.ok ? result.errors : undefined;
  return (
    <ScriptStepCard
      index={index}
      total={total}
      step={step}
      preview={result?.ok ? result.preview : undefined}
      errors={errors}
      showErrors={false}
      sending={false}
      sendLabel={sendLabel(step)}
      place={place}
      onChange={onChange}
      onMove={() => undefined}
      onRemove={() => undefined}
    />
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
  const id = templateId(step);
  if (id === "uton-burn") return "Send burn";
  if (id === "burn-notification") return "Send burn notification";
  if (id === "withdraw") return "Send withdraw";
  return "Send";
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
