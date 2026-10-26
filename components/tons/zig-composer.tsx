"use client";

import { useEffect, useRef, useState } from "react";
import { PathRunBar, type PathNotice } from "@/components/tons/path-run-bar";
import { SourceList } from "@/components/tons/source-block";
import { TonsWalletDesk, tonsInFlightLabel } from "@/components/tons/wallet-desk";
import { zigExplorerTxUrl } from "@/lib/valdora";
import { valdoraPathSource } from "@/lib/valdora-path";
import {
  compilePathRun,
  pathLookupNote,
  readZigPathDefaults,
  readZigSendResult,
  type ZigPathDefaultsOk,
} from "@/lib/valdora-path-run";
import { isZigAddress, ZIG_FUNDED_WALLET_ADDRESS } from "@/lib/zig-funded-wallet-public";

export function ZigComposer({ deskAddress }: { deskAddress: string }) {
  const initial = deskAddress.trim() || ZIG_FUNDED_WALLET_ADDRESS;
  const [localWallet, setLocalWallet] = useState(true);
  const [address, setAddress] = useState(initial);
  const [sending, setSending] = useState(false);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [notice, setNotice] = useState<PathNotice | null>(null);
  const [lookupNote, setLookupNote] = useState<string | null>(null);
  const [deskNotice, setDeskNotice] = useState<string | null>(null);
  const [pathIdText, setPathIdText] = useState("");
  const [pathId, setPathId] = useState<number | null>(null);
  const sendingRef = useRef(false);
  const touchedRef = useRef(false);
  const pathIdRef = useRef<number | null>(null);
  pathIdRef.current = pathId;

  useEffect(() => {
    let cancel = false;
    void (async () => {
      const defaults = await fetchPathDefaults(address);
      if (cancel || !defaults) {
        if (!cancel) setLookupNote("The LCD lookup did not answer.");
        return;
      }
      if (!defaults.ok) {
        setLookupNote(defaults.message);
        return;
      }
      if (defaults.owner && isZigAddress(defaults.owner) && defaults.owner !== address) {
        setAddress(defaults.owner);
      }
      if (!touchedRef.current) {
        setPathId(defaults.suggested_id);
        setPathIdText(defaults.suggested_id === null ? "" : String(defaults.suggested_id));
      }
      setLookupNote(pathLookupNote(defaults));
    })();
    return () => {
      cancel = true;
    };
  }, [localWallet, address]);

  async function runPath() {
    if (sendingRef.current) return;
    if (!localWallet) {
      setNotice({ tone: "bad", text: "The desk wallet is the only signer. Nothing was sent." });
      return;
    }
    sendingRef.current = true;
    setSending(true);
    setSendingId("path");
    setNotice(null);
    try {
      const defaults = await fetchPathDefaults(address);
      if (!defaults) {
        setNotice({ tone: "bad", text: "The LCD lookup did not answer. Nothing was sent." });
        return;
      }
      if (!defaults.ok) {
        setNotice({ tone: "bad", text: `${defaults.message} Nothing was sent.` });
        return;
      }
      setLookupNote(pathLookupNote(defaults));
      if (defaults.paused) {
        setNotice({ tone: "bad", text: "The staker paused query returned true. Nothing was sent." });
        return;
      }
      const id = touchedRef.current ? pathIdRef.current : (defaults.suggested_id ?? pathIdRef.current);
      if (id === null) {
        setNotice({ tone: "bad", text: "No withdrawal request id. Nothing was sent." });
        return;
      }
      const sender = defaults.owner && isZigAddress(defaults.owner) ? defaults.owner : address;
      const compiled = compilePathRun({ id, sender });
      if (!compiled.ok) {
        setNotice({ tone: "bad", text: compiled.message });
        return;
      }
      const response = await fetch("/api/zig/send", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          messages: compiled.messages,
          ...(compiled.memo ? { memo: compiled.memo } : {}),
        }),
      });
      const payload: unknown = await response.json().catch(() => null);
      const result = readZigSendResult(payload);
      if (!result) {
        setNotice({
          tone: "bad",
          text: "The send reply could not be read. Check the account before trying again, so it is not sent twice.",
        });
        return;
      }
      if (!result.ok) {
        setNotice({ tone: "bad", text: result.text });
        return;
      }
      setNotice({
        tone: "good",
        text: `Broadcast ${result.txHash} at height ${result.height}.`,
        href: zigExplorerTxUrl(result.txHash),
        hrefLabel: "View the transaction",
      });
    } catch {
      setNotice({
        tone: "bad",
        text: "The send did not finish. Check the account before trying again, so it is not sent twice.",
      });
    } finally {
      sendingRef.current = false;
      setSending(false);
      setSendingId(null);
    }
  }

  const pathDisabled = sending || pathId === null || !localWallet || !isZigAddress(address);

  return (
    <section className="ton-section" id="message" aria-labelledby="ton-message-title">
      <h2 id="ton-message-title">Path</h2>
      <nav className="ton-contents" aria-label="Path">
        <a href="#path-run">Run path</a>
        <a href="#query-totals">Query totals</a>
        <a href="#execute">Execute</a>
        <a href="#handler">Handler</a>
      </nav>
      <TonsWalletDesk
        localWallet={localWallet}
        address={address}
        sending={sending}
        notice={deskNotice}
        onUseFunded={() => {
          setLocalWallet(true);
          setDeskNotice(null);
        }}
        onDisconnect={() => {
          setLocalWallet(false);
          setDeskNotice("The desk wallet is the only signer.");
        }}
      />
      <label className="ton-field">
        <span>withdrawal request id</span>
        <input
          inputMode="numeric"
          autoComplete="off"
          aria-label="withdrawal request id"
          value={pathIdText}
          onChange={(event) => {
            const raw = event.target.value;
            touchedRef.current = true;
            setPathIdText(raw);
            setPathId(parseIdInput(raw));
            setNotice(null);
          }}
        />
      </label>
      <PathRunBar
        sending={sendingId === "path"}
        label={sendingId === "path" ? tonsInFlightLabel() : "Run path"}
        disabled={pathDisabled}
        notice={notice}
        lookupNote={lookupNote}
        onRun={() => void runPath()}
      />
      <div className="ton-steps">
        <PathCards />
      </div>
    </section>
  );
}

export function PathCards() {
  return (
    <>
      <ReadOnlyCard
        id="query-totals"
        titleId="query-totals-title"
        kicker="LCD"
        title="total_completed_unbondings"
        sources={[
          valdoraPathSource.queryTotals,
          valdoraPathSource.queryTotalsSample,
          valdoraPathSource.queryPaused,
          valdoraPathSource.queryProtocol,
        ]}
        hint="Smart queries are base64 JSON on the LCD. paused and protocol_info are status reads. They are not chain messages."
      />
      <ReadOnlyCard
        id="execute"
        titleId="execute-title"
        kicker="CosmWasm"
        title="withdraw_unbonded_by_id"
        sources={[valdoraPathSource.execute]}
        hint="One MsgExecuteContract through CosmJS with automatic gas. sender is the desk zig1 address. funds is an empty list. The schema field is withdrawal_request_id. The key id fails schema parsing on code id 179."
      />
      <ReadOnlyCard
        id="handler"
        titleId="handler-title"
        kicker="stzig-staker"
        title="Handler storage"
        sources={[valdoraPathSource.handler]}
        hint="Storage operations inside the staker execute. This card does not send."
      />
    </>
  );
}

function ReadOnlyCard({
  id,
  titleId,
  kicker,
  title,
  sources,
  hint,
}: {
  id: string;
  titleId: string;
  kicker: string;
  title: string;
  sources: readonly { file: string; code: string }[];
  hint: string;
}) {
  return (
    <section className="ton-step" id={id} aria-labelledby={titleId}>
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">{kicker}</p>
          <h2 id={titleId}>{title}</h2>
        </div>
      </div>
      <SourceList sources={sources} />
      <p className="ton-hint">{hint}</p>
    </section>
  );
}

function parseIdInput(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const id = Number(trimmed);
  if (!Number.isSafeInteger(id) || id < 0) return null;
  return id;
}

async function fetchPathDefaults(
  owner: string,
): Promise<ZigPathDefaultsOk | { ok: false; message: string } | null> {
  try {
    const response = await fetch("/api/zig/path-defaults", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(owner ? { owner } : {}),
    });
    const payload: unknown = await response.json().catch(() => null);
    return readZigPathDefaults(payload);
  } catch {
    return null;
  }
}
