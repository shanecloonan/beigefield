"use client";

import { useSyncExternalStore } from "react";
import { utonDeskLoads, type UtonTemplateId } from "@/lib/uton-templates";

const loadListeners = new Set<(templateId: UtonTemplateId) => void>();
const sendingListeners = new Set<() => void>();
let deskSending = false;

export function publishDeskSending(sending: boolean) {
  deskSending = sending;
  for (const listener of sendingListeners) listener();
}

function subscribeSending(listener: () => void) {
  sendingListeners.add(listener);
  return () => {
    sendingListeners.delete(listener);
  };
}

function readSending() {
  return deskSending;
}

function useDeskSending() {
  return useSyncExternalStore(subscribeSending, readSending, () => false);
}

export function requestDeskLoad(templateId: UtonTemplateId) {
  if (deskSending) return;
  for (const listener of loadListeners) listener(templateId);
}

export function subscribeDeskLoad(listener: (templateId: UtonTemplateId) => void) {
  loadListeners.add(listener);
  return () => {
    loadListeners.delete(listener);
  };
}

export function DeskLoaders({
  sending,
  onLoad,
}: {
  sending: boolean;
  onLoad: (templateId: UtonTemplateId) => void;
}) {
  return (
    <div className="ton-load" role="group" aria-label="Load a known message">
      {utonDeskLoads.map((item) => (
        <button
          key={item.id}
          type="button"
          className="ton-button ton-button-quiet ton-button-tiny"
          disabled={sending}
          onClick={() => onLoad(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export function DeskLoadButton({
  templateId,
  children,
}: {
  templateId: UtonTemplateId;
  children: string;
}) {
  const sending = useDeskSending();

  return (
    <button
      type="button"
      className="ton-button ton-button-quiet ton-button-tiny"
      disabled={sending}
      onClick={() => {
        requestDeskLoad(templateId);
        document.getElementById("message")?.scrollIntoView({ behavior: "smooth", block: "start" });
        if (window.location.hash !== "#message") {
          history.replaceState(null, "", "#message");
        }
      }}
    >
      {children}
    </button>
  );
}
