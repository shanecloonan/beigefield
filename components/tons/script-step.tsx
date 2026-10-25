"use client";

import type { ReactNode } from "react";
import type { BodyField, MessageBody, ScriptStep, StepErrors, StepPreview } from "@/lib/ton-message";
import type { PathSource } from "@/lib/uton-path";
import { SourceList } from "@/components/tons/source-block";
import { utonTemplateBody, utonTemplateById } from "@/lib/uton-templates";

export type StepPlace = {
  anchor: string;
  kicker: string;
  title: string;
  sources: readonly PathSource[];
};

const bodyKinds: Array<{ kind: MessageBody["kind"]; label: string }> = [
  { kind: "empty", label: "Empty" },
  { kind: "comment", label: "Comment" },
  { kind: "fields", label: "Fields" },
  { kind: "boc", label: "BoC" },
];

export function ScriptStepCard({
  index,
  total,
  step,
  preview,
  errors,
  showErrors,
  sending,
  sendLabel,
  sendDisabled,
  place,
  status,
  onChange,
  onMove,
  onRemove,
  onSend,
}: {
  index: number;
  total: number;
  step: ScriptStep;
  preview?: StepPreview;
  errors?: StepErrors;
  showErrors: boolean;
  sending: boolean;
  sendLabel: string;
  sendDisabled: boolean;
  place?: StepPlace;
  status?: ReactNode;
  onChange: (step: ScriptStep) => void;
  onMove: (direction: -1 | 1) => void;
  onRemove: () => void;
  onSend: () => void;
}) {
  const visible = showErrors ? errors : undefined;
  const destinationId = `${step.id}-destination`;
  const amountId = `${step.id}-amount`;
  const template =
    step.body.kind === "fields" && step.body.templateId
      ? utonTemplateById(step.body.templateId)
      : undefined;
  const stake = template?.id === "stake-ton";
  const burn = template?.id === "uton-burn";
  const notify = template?.id === "burn-notification";
  const withdraw = template?.id === "withdraw";
  const tailored = Boolean(place) || stake || burn || notify || withdraw;
  const anchor =
    place?.anchor ??
    (stake
      ? "stake-form"
      : burn
        ? "burn-form"
        : notify
          ? "notify-form"
          : withdraw
            ? "withdraw-form"
            : undefined);

  function setBody(body: MessageBody) {
    onChange({ ...step, body });
  }

  function setField(id: string, next: BodyField) {
    if (step.body.kind !== "fields") return;
    setBody({
      ...step.body,
      fields: step.body.fields.map((field) => (field.id === id ? next : field)),
    });
  }

  function moveField(fieldIndex: number, direction: -1 | 1) {
    if (step.body.kind !== "fields") return;
    const target = fieldIndex + direction;
    const fields = step.body.fields.slice();
    const current = fields[fieldIndex];
    const swap = fields[target];
    if (!current || !swap || target < 0 || target >= fields.length) return;
    fields[fieldIndex] = swap;
    fields[target] = current;
    setBody({ ...step.body, fields });
  }

  return (
    <section className="ton-step" id={anchor} aria-labelledby={`${step.id}-title`}>
      <div className="ton-step-head">
        <div>
          <p className="ton-kicker">
            {place
              ? place.kicker
              : stake
                ? "Step 1"
                : burn
                  ? "Step 2"
                  : notify
                    ? "Step 3"
                    : withdraw
                      ? "Step 5"
                      : preview
                        ? "Ready"
                        : "Draft"}
            {place || !template ? "" : ` · ${template.label}`}
          </p>
          <h2 id={`${step.id}-title`}>
            {place
              ? place.title
              : stake
                ? "Stake native TON"
                : burn
                  ? "uTON burn"
                  : notify
                    ? "Burn notification"
                    : withdraw
                      ? "Withdraw"
                      : `Step ${index + 1}`}
          </h2>
        </div>
        {tailored ? null : (
          <div className="ton-step-actions">
            <button
              type="button"
              className="ton-button ton-button-quiet ton-button-tiny"
              onClick={() => onMove(-1)}
              disabled={index === 0 || sending}
            >
              Up
            </button>
            <button
              type="button"
              className="ton-button ton-button-quiet ton-button-tiny"
              onClick={() => onMove(1)}
              disabled={index === total - 1 || sending}
            >
              Down
            </button>
            <button
              type="button"
              className="ton-button ton-button-quiet ton-button-tiny"
              onClick={onRemove}
              disabled={sending}
            >
            Remove
          </button>
          </div>
        )}
      </div>

      {place ? <SourceList sources={place.sources} /> : null}
      {place ? null : stake ? (
        <p className="ton-section-copy">
          Opcode 0x1003 to proxy_ton. The TON on this message is the deposit.
          Query id, user, and response stay editable.
        </p>
      ) : null}
      {place || !burn ? null : (
        <p className="ton-section-copy">
          Opcode 0x595f07bc to your uTON jetton wallet. The uTON amount is a
          field below. Proxy id and forward value travel in the custom payload.
        </p>
      )}
      {place || !notify ? null : (
        <p className="ton-section-copy">
          Opcode 0x7bdd97de to the minter. The owner address is stored before
          the uTON amount. The jetton wallet has already reduced its balance
          before it sends this. The message is bounceable. If the minter
          rejects it, for example an invalid proxy id, the bounce returns to
          on_bounce on the wallet.
        </p>
      )}
      {place || !withdraw ? null : (
        <p className="ton-section-copy">
          Opcode 0x4502 to the pending withdraw contract. Send it only after
          withdraw_pending_time has elapsed. This call starts that contract
          withdraw path, which queries the minter.{" "}
          <a href="#payout-form">That query is step 6.</a>
        </p>
      )}

      <label className="ton-field" htmlFor={destinationId}>
        <span>
          {stake
            ? "proxy_ton address"
            : burn
              ? "Your uTON jetton wallet"
              : notify
                ? "Minter"
                : withdraw
                  ? "Pending withdraw contract"
                  : "Destination"}
        </span>
        <input
          id={destinationId}
          value={step.destination}
          onChange={(event) => onChange({ ...step, destination: event.target.value })}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder={
            stake
              ? "Paste proxy_ton"
              : burn
                ? "Paste your uTON wallet"
                : notify
                  ? "Minter address"
                  : withdraw
                    ? "Paste the pending withdraw"
                    : "EQ… or UQ…"
          }
          aria-invalid={Boolean(visible?.destination)}
        />
      </label>
      {place || !template ? null : <p className="ton-hint">{template.destinationHint}</p>}
      {visible?.destination ? <p className="ton-error">{visible.destination}</p> : null}

      <div className="ton-field">
        <span id={amountId}>
          {stake ? "TON to stake" : burn || notify || withdraw ? "TON attached" : "Value"}
        </span>
        <div className="ton-choice" role="group" aria-label="Value unit">
          <button
            type="button"
            className="ton-button ton-button-quiet ton-button-tiny"
            aria-pressed={step.unit === "ton"}
            onClick={() => onChange({ ...step, unit: "ton" })}
          >
            TON
          </button>
          <button
            type="button"
            className="ton-button ton-button-quiet ton-button-tiny"
            aria-pressed={step.unit === "nanoton"}
            onClick={() => onChange({ ...step, unit: "nanoton" })}
          >
            Nanotons
          </button>
        </div>
        <div className="ton-amount">
          <input
            aria-labelledby={amountId}
            value={step.amount}
            onChange={(event) => onChange({ ...step, amount: event.target.value })}
            inputMode="decimal"
            autoComplete="off"
            placeholder={step.unit === "ton" ? "0.1" : "100000000"}
            aria-invalid={Boolean(visible?.amount)}
          />
          <span>{step.unit === "ton" ? "TON" : "Nano"}</span>
        </div>
      </div>
      {place || !template ? null : <p className="ton-hint">{template.valueHint}</p>}
      {visible?.amount ? <p className="ton-error">{visible.amount}</p> : null}

      <label className="ton-check">
        <input
          type="checkbox"
          checked={step.bounceable}
          onChange={(event) => onChange({ ...step, bounceable: event.target.checked })}
        />
        <span>Bounceable destination</span>
      </label>
      {place ? null : (
      <p className="ton-hint">
        {stake
          ? "On by default. Leave it on so proxy_ton can return the TON if it does not accept the stake."
          : burn
            ? "On by default. Leave it on so your jetton wallet can return the attached TON if it does not accept the burn."
            : notify
              ? "On by default. If the minter rejects the notification, the bounce returns to on_bounce on the jetton wallet."
              : withdraw
                ? "On by default. Leave it on so the pending withdraw can return the attached TON if it does not accept the message."
                : "Bounceable asks the destination to return the value if it cannot accept the message."}
      </p>
      )}

      <div className="ton-field">
        {tailored ? null : (
          <>
        <span>Body</span>
        <div className="ton-choice" role="group" aria-label="Message body">
          {bodyKinds.map((option) => (
            <button
              key={option.kind}
              type="button"
              className="ton-button ton-button-quiet ton-button-tiny"
              aria-pressed={step.body.kind === option.kind}
              onClick={() => {
                if (option.kind === "fields" && template) {
                  setBody({ kind: "fields", opcode: "", opcodeBits: "32", fields: [] });
                  return;
                }
                setBody(bodyForKind(option.kind, step.body));
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
        <label className="ton-field ton-known">
          <span>Known message</span>
          <select
            aria-label="Known message"
            value={template?.id ?? ""}
            onChange={(event) => {
              const id = event.target.value;
              if (!id) {
                if (step.body.kind === "fields" && step.body.templateId) {
                  onChange({
                    ...step,
                    body: { kind: "fields", opcode: "", opcodeBits: "32", fields: [] },
                  });
                }
                return;
              }
              const next = utonTemplateById(id);
              if (!next || next.id !== "stake-ton") return;
              onChange({
                ...step,
                bounceable: next.bounceable,
                body: utonTemplateBody(next),
              });
            }}
          >
            <option value="">Custom</option>
            <option value="stake-ton">Stake native TON</option>
          </select>
        </label>
          </>
        )}
        <BodyEditor
          stepId={step.id}
          body={step.body}
          fieldErrors={visible?.fields}
          quiet={Boolean(place)}
          onChange={setBody}
          onField={setField}
          onMoveField={moveField}
        />
      </div>
      {visible?.body ? <p className="ton-error">{visible.body}</p> : null}

      {preview ? (
        <dl className="ton-preview-list">
          <div>
            <dt>To</dt>
            <dd>{preview.address}</dd>
          </div>
          <div>
            <dt>Value</dt>
            <dd>
              {preview.valueLabel}
              <span className="ton-preview-nano"> · {preview.nanotons} nanotons</span>
            </dd>
          </div>
          <div>
            <dt>Bounce</dt>
            <dd>{preview.bounceable ? "Bounceable" : "Non-bounceable"}</dd>
          </div>
          <div>
            <dt>Body</dt>
            <dd>{preview.bodyLabel}</dd>
          </div>
        </dl>
      ) : null}

      <button
        type="button"
        className={tailored ? "ton-button" : "ton-button ton-button-quiet"}
        onClick={onSend}
        disabled={sendDisabled}
      >
        {sendLabel}
      </button>
      {status}
    </section>
  );
}

function BodyEditor({
  stepId,
  body,
  fieldErrors,
  quiet,
  onChange,
  onField,
  onMoveField,
}: {
  stepId: string;
  body: MessageBody;
  fieldErrors?: Record<string, string>;
  quiet?: boolean;
  onChange: (body: MessageBody) => void;
  onField: (id: string, field: BodyField) => void;
  onMoveField: (index: number, direction: -1 | 1) => void;
}) {
  if (body.kind === "empty") {
    return <p className="ton-hint">No payload. The message carries value only.</p>;
  }

  if (body.kind === "comment") {
    return (
      <>
        <textarea
          value={body.text}
          onChange={(event) => onChange({ kind: "comment", text: event.target.value })}
          rows={3}
          placeholder="Text carried in the message"
          aria-label="Comment"
        />
        <p className="ton-hint">Text carried in the message body.</p>
      </>
    );
  }

  if (body.kind === "boc") {
    return (
      <>
        <textarea
          className="ton-boc"
          value={body.hex}
          onChange={(event) => onChange({ kind: "boc", hex: event.target.value })}
          rows={4}
          spellCheck={false}
          placeholder="Hex BoC"
          aria-label="BoC"
        />
        <p className="ton-hint">Hex BoC of one cell. A base64 BoC works as well.</p>
      </>
    );
  }

  const template = body.templateId ? utonTemplateById(body.templateId) : undefined;

  return (
    <div className="ton-fields">
      {quiet || !template ? null : <p className="ton-hint">{template.detail}</p>}
      <div className="ton-split">
        <label className="ton-field">
          <span>Opcode</span>
          <input
            value={body.opcode}
            onChange={(event) => onChange({ ...body, opcode: event.target.value })}
            placeholder="0x0 or blank"
            spellCheck={false}
            autoComplete="off"
          />
        </label>
        <label className="ton-field">
          <span>Bits</span>
          <input
            value={body.opcodeBits}
            onChange={(event) => onChange({ ...body, opcodeBits: event.target.value })}
            inputMode="numeric"
            aria-label="Opcode bit width"
          />
        </label>
      </div>
      {template ? null : (
        <p className="ton-hint">
          The opcode is stored first as an unsigned integer. Leave it blank to start with the fields.
        </p>
      )}
      {body.fields.map((field, index) => (
        <div className="ton-substep" key={field.id}>
          <div className="ton-substep-head">
            <label>
              <span className="ton-mini">{field.label ?? `Field ${index + 1}`}</span>
              {template ? (
                <span className="ton-field-kind">{fieldKindLabel(field.kind)}</span>
              ) : (
                <select
                  value={field.kind}
                  aria-label={`Field ${index + 1} type`}
                  onChange={(event) =>
                    onField(field.id, fieldOfKind(field.id, event.target.value))
                  }
                >
                  <option value="uint">Unsigned integer</option>
                  <option value="coins">Coins</option>
                  <option value="address">Address</option>
                  <option value="text">Text tail</option>
                </select>
              )}
            </label>
            {template ? null : (
            <div className="ton-step-actions">
              <button
                type="button"
                className="ton-button ton-button-quiet ton-button-tiny"
                onClick={() => onMoveField(index, -1)}
                disabled={index === 0}
              >
                Up
              </button>
              <button
                type="button"
                className="ton-button ton-button-quiet ton-button-tiny"
                onClick={() => onMoveField(index, 1)}
                disabled={index === body.fields.length - 1}
              >
                Down
              </button>
              <button
                type="button"
                className="ton-button ton-button-quiet ton-button-tiny"
                onClick={() =>
                  onChange({
                    ...body,
                    fields: body.fields.filter((item) => item.id !== field.id),
                  })
                }
              >
                Remove
              </button>
            </div>
            )}
          </div>
          <FieldInputs field={field} onField={onField} />
          {quiet ? null : stakeFieldHint(body.templateId, field.id) ? (
            <p className="ton-hint">{stakeFieldHint(body.templateId, field.id)}</p>
          ) : null}
          {fieldErrors?.[field.id] ? (
            <p className="ton-error">{fieldErrors[field.id]}</p>
          ) : null}
        </div>
      ))}
      {template ? null : (
        <button
          type="button"
          className="ton-button ton-button-quiet ton-button-tiny"
          onClick={() =>
            onChange({
              ...body,
              fields: [
                ...body.fields,
                { id: `${stepId}-field-${body.fields.length + 1}-${Date.now()}`, kind: "uint", bits: "32", value: "" },
              ],
            })
          }
        >
          Add field
        </button>
      )}
    </div>
  );
}

function stakeFieldHint(templateId: string | undefined, fieldId: string): string | null {
  if (templateId === "stake-ton") {
    if (fieldId === "query_id") return "64 bits. Starts at 0.";
    if (fieldId === "user") return "Receives the minted uTON. Starts as the desk wallet.";
    if (fieldId === "response") return "Receives excess gas. Starts as the desk wallet.";
  }
  if (templateId === "uton-burn") {
    if (fieldId === "query_id") return "64 bits. Starts at 0.";
    if (fieldId === "amount") return "uTON to burn, in nanotons.";
    if (fieldId === "response") return "Receives excess gas. Starts as the desk wallet.";
    if (fieldId === "proxy_id") {
      return "32 bits, stored at dictionary key 0. Starts at 3. Not on the minter whitelist.";
    }
    if (fieldId === "fwd_value") {
      return "Nanotons in the custom payload. Starts at 10000000. The empty forward cell is not editable.";
    }
  }
  if (templateId === "burn-notification") {
    if (fieldId === "query_id") return "64 bits. Starts at 0.";
    if (fieldId === "owner") return "Stored before the uTON amount. Starts as the desk wallet.";
    if (fieldId === "withdraw_id") return "64 bits. Starts at 0.";
    if (fieldId === "amount") return "uTON in the notification, in nanotons. Left blank.";
    if (fieldId === "proxy_id") {
      return "32 bits. Starts at 3. A missing whitelist entry throws, and the message bounces.";
    }
    if (fieldId === "response") return "Receives excess gas. Starts as the desk wallet.";
    if (fieldId === "fwd_value") {
      return "Nanotons. Starts at 10000000. The empty forward cell is not editable.";
    }
  }
  if (templateId === "withdraw") {
    if (fieldId === "query_id") return "64 bits. Starts at 0.";
    if (fieldId === "recipient") return "Receives the withdrawn TON. Starts as the desk wallet.";
    if (fieldId === "response") return "Receives excess gas. Starts as the desk wallet.";
  }
  return null;
}

function fieldKindLabel(kind: BodyField["kind"]): string {
  if (kind === "uint") return "Unsigned integer";
  if (kind === "coins") return "Nanotons";
  if (kind === "address") return "Address";
  return "Text";
}

function FieldInputs({
  field,
  onField,
}: {
  field: BodyField;
  onField: (id: string, field: BodyField) => void;
}) {
  if (field.kind === "uint") {
    return (
      <div className="ton-split">
        <label className="ton-field">
          <span>Value</span>
          <input
            value={field.value}
            onChange={(event) => onField(field.id, { ...field, value: event.target.value })}
            spellCheck={false}
            autoComplete="off"
          />
        </label>
        <label className="ton-field">
          <span>Bits</span>
          <input
            value={field.bits}
            onChange={(event) => onField(field.id, { ...field, bits: event.target.value })}
            inputMode="numeric"
          />
        </label>
      </div>
    );
  }

  if (field.kind === "coins") {
    return (
      <label className="ton-field">
        <span>Nanotons</span>
        <input
          value={field.value}
          onChange={(event) => onField(field.id, { ...field, value: event.target.value })}
          inputMode="numeric"
          autoComplete="off"
        />
      </label>
    );
  }

  if (field.kind === "address") {
    return (
      <label className="ton-field">
        <span>Address</span>
        <input
          value={field.value}
          onChange={(event) => onField(field.id, { ...field, value: event.target.value })}
          spellCheck={false}
          autoComplete="off"
          autoCapitalize="off"
        />
      </label>
    );
  }

  return (
    <label className="ton-field">
      <span>Text</span>
      <textarea
        value={field.value}
        onChange={(event) => onField(field.id, { ...field, value: event.target.value })}
        rows={2}
      />
    </label>
  );
}

function bodyForKind(kind: MessageBody["kind"], current: MessageBody): MessageBody {
  if (current.kind === kind) return current;
  if (kind === "empty") return { kind: "empty" };
  if (kind === "comment") return { kind: "comment", text: "" };
  if (kind === "boc") return { kind: "boc", hex: "" };
  return { kind: "fields", opcode: "", opcodeBits: "32", fields: [] };
}

function fieldOfKind(id: string, kind: string): BodyField {
  if (kind === "coins") return { id, kind: "coins", value: "" };
  if (kind === "address") return { id, kind: "address", value: "" };
  if (kind === "text") return { id, kind: "text", value: "" };
  return { id, kind: "uint", bits: "32", value: "" };
}
