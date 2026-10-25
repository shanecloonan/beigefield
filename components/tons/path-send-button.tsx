"use client";

import { useState } from "react";

export function PathSendButton({ detail }: { detail: string }) {
  const [note, setNote] = useState<string | null>(null);

  return (
    <>
      <button type="button" className="ton-button" onClick={() => setNote(detail)}>
        Send
      </button>
      {note ? (
        <p className="ton-error" role="status">
          {note}
        </p>
      ) : null}
    </>
  );
}
