"use client";

import { useState, type ReactNode } from "react";
import { THEME, TonConnectUI, TonConnectUIProvider } from "@tonconnect/ui-react";
import {
  TON_MAINNET_CHAIN,
  classifySendError,
  connectFailureMessage,
  isMainnetChain,
} from "@/lib/ton-message";

const paperPalette = {
  accent: "#2b241c",
  connectButton: {
    background: "#2b241c",
    foreground: "#f3eee6",
  },
  background: {
    primary: "#f8f4ed",
    secondary: "#f3eee6",
    segment: "#e4dbcd",
    tint: "#e4dbcd",
    qr: "#ffffff",
  },
  text: {
    primary: "#2b241c",
    secondary: "#5a4e44",
  },
  icon: {
    primary: "#2b241c",
    secondary: "#5a4e44",
    tertiary: "#5a4e44",
    success: "#2b241c",
    error: "#2b241c",
  },
};

let mainnetUi: TonConnectUI | null = null;
let connectNoticeSnapshot: string | null = null;
const connectNoticeListeners = new Set<(message: string | null) => void>();

function publishConnectNotice(message: string | null) {
  connectNoticeSnapshot = message;
  for (const listener of connectNoticeListeners) listener(message);
}

export function subscribeConnectNotice(
  listener: (message: string | null) => void,
) {
  connectNoticeListeners.add(listener);
  listener(connectNoticeSnapshot);
  return () => {
    connectNoticeListeners.delete(listener);
  };
}

export function reportConnectNotice(message: string | null) {
  publishConnectNotice(message);
}

export function clearConnectNotice() {
  reportConnectNotice(null);
}

function mainnetUiFor(manifestUrl: string): TonConnectUI {
  if (mainnetUi) return mainnetUi;

  const ui = new TonConnectUI({
    manifestUrl,
    language: "en",
    uiPreferences: {
      theme: THEME.LIGHT,
      borderRadius: "s",
      colorsSet: {
        [THEME.LIGHT]: paperPalette,
      },
    },
  });
  // Session restore waits for the next frame. Pin mainnet, and subscribe,
  // before that restore so a testnet wallet is refused and the refusal is kept.
  ui.setConnectionNetwork(TON_MAINNET_CHAIN);
  ui.onStatusChange(
    (wallet) => {
      if (wallet && isMainnetChain(wallet.account.chain)) {
        publishConnectNotice(null);
      }
    },
    (error) => {
      publishConnectNotice(
        connectFailureMessage(classifySendError(error), manifestUrl),
      );
    },
  );
  mainnetUi = ui;
  return ui;
}

export function TonProvider({
  manifestUrl,
  children,
}: {
  manifestUrl: string;
  children: ReactNode;
}) {
  const [ui] = useState<TonConnectUI | null>(() => {
    if (typeof window === "undefined") return null;
    return mainnetUiFor(manifestUrl);
  });

  if (!ui) return children;

  return <TonConnectUIProvider instance={ui}>{children}</TonConnectUIProvider>;
}
