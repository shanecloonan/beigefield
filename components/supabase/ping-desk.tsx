"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { formatTimestamp } from "@/lib/supabase/format";
import {
  fetchPingTests,
  insertPingTest,
  PING_NOTE_MAX,
  pingNote,
  type PingRow,
} from "@/lib/supabase/ping";

type PingDeskProps = {
  initialRows: PingRow[];
  initialError: string | null;
  canWrite: boolean;
};

export function PingDesk({ initialRows, initialError, canWrite }: PingDeskProps) {
  const router = useRouter();
  const [note, setNote] = useState("");
  const [localRows, setLocalRows] = useState<PingRow[] | null>(null);
  const [status, setStatus] = useState<string | null>(initialError);
  const [pending, setPending] = useState(false);
  const [tone, setTone] = useState<"error" | "good">(initialError ? "error" : "good");
  const rows = localRows ?? initialRows;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canWrite || pending) return;

    const text = pingNote(note);
    const optimisticId = `pending-${Date.now()}`;
    const optimistic: PingRow = {
      id: optimisticId,
      note: text,
      created_at: new Date().toISOString(),
    };

    setPending(true);
    setTone("good");
    setStatus(null);
    setLocalRows((current) => [optimistic, ...(current ?? initialRows)]);

    const inserted = await insertPingTest(text);
    if (inserted.error || !inserted.row) {
      setLocalRows((current) => (current ?? initialRows).filter((row) => row.id !== optimisticId));
      setTone("error");
      setStatus(inserted.error ?? "Insert failed.");
      setPending(false);
      return;
    }

    const saved = inserted.row;
    const latest = await fetchPingTests();
    setLocalRows((current) => {
      const previous = (current ?? initialRows).filter((row) => row.id !== optimisticId && row.id !== saved.id);
      if (latest.error) return [saved, ...previous];
      if (latest.rows.some((row) => row.id === saved.id)) return latest.rows;
      return [saved, ...latest.rows];
    });
    setNote("");
    setTone("good");
    setStatus("Saved.");
    setPending(false);
    router.refresh();
  }

  return (
    <div>
      <form className="ton-form" onSubmit={onSubmit}>
        <label className="ton-field">
          <span>Note</span>
          <input
            name="note"
            value={note}
            maxLength={PING_NOTE_MAX}
            autoComplete="off"
            placeholder="A short note"
            disabled={!canWrite || pending}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
        <p className="ton-hint">Leave this blank to store the current time.</p>
        <button className="ton-button ton-submit" type="submit" disabled={!canWrite || pending}>
          {pending ? "Saving" : "Insert row"}
        </button>
      </form>
      {status ? (
        <p className={tone === "error" ? "ton-error" : "ton-good"} role="status">
          {status}
        </p>
      ) : null}
      {rows.length === 0 ? (
        <p className="ton-hint">No rows yet.</p>
      ) : (
        <div className="sb-scroll">
          <table className="sb-table">
            <caption>ping_tests</caption>
            <thead>
              <tr>
                <th scope="col">id</th>
                <th scope="col">note</th>
                <th scope="col">created_at</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} data-pending={row.id.startsWith("pending-") ? true : undefined}>
                  <td className="ton-mono">{row.id.startsWith("pending-") ? "…" : row.id}</td>
                  <td>{row.note ?? "—"}</td>
                  <td>{formatTimestamp(row.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
