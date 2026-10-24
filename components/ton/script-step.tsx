"use client";

import type { BodyField, MessageBody, ScriptStep, StepErrors, StepPreview } from "@/lib/ton-message";

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
  sendDisabled,
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
  sendDisabled: boolean;
  onChange: (step: ScriptStep) => void;
  onMove: (direction: -1 | 1) => void;
  onRemove: () => void;
  onSend: () => void;
}) {
  const visible = showErrors ? errors : undefined;
  const destinationId = `${step.id}-destination`;
  const amountId = `${step.id}-amount`;

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
    <section className="ton-step" aria-labelledby={`${step.id}-title`}>
      <div className="ton-step-head">
        <h2 id={`${step.id}-title`}>Step {index + 1}</h2>
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
      </div>

      <label className="ton-field" htmlFor={destinationId}>
        <span>Destination</span>
        <input
          id={destinationId}
          value={step.destination}
          onChange={(event) => onChange({ ...step, destination: event.target.value })}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder="EQ… or UQ…"
          aria-invalid={Boolean(visible?.destination)}
        />
      </label>
      {visible?.destination ? <p className="ton-error">{visible.destination}</p> : null}

      <div className="ton-field">
        <span id={amountId}>Value</span>
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
        <input
          aria-labelledby={amountId}
          value={step.amount}
          onChange={(event) => onChange({ ...step, amount: event.target.value })}
          inputMode="decimal"
          autoComplete="off"
          placeholder={step.unit === "ton" ? "0.1" : "100000000"}
          aria-invalid={Boolean(visible?.amount)}
        />
      </div>
      {visible?.amount ? <p className="ton-error">{visible.amount}</p> : null}

      <label className="ton-check">
        <input
          type="checkbox"
          checked={step.bounceable}
          onChange={(event) => onChange({ ...step, bounceable: event.target.checked })}
        />
        <span>Bounceable destination</span>
      </label>

      <div className="ton-field">
        <span>Body</span>
        <div className="ton-choice" role="group" aria-label="Message body">
          {bodyKinds.map((option) => (
            <button
              key={option.kind}
              type="button"
              className="ton-button ton-button-quiet ton-button-tiny"
              aria-pressed={step.body.kind === option.kind}
              onClick={() => setBody(bodyForKind(option.kind, step.body))}
            >
              {option.label}
            </button>
          ))}
        </div>
        <BodyEditor
          stepId={step.id}
          body={step.body}
          fieldErrors={visible?.fields}
          onChange={setBody}
          onField={setField}
          onMoveField={moveField}
        />
      </div>
      {visible?.body ? <p className="ton-error">{visible.body}</p> : null}

      {preview ? (
        <p className="ton-preview">
          {preview.bounceable ? "Bounceable" : "Non-bounceable"} {preview.valueLabel} to{" "}
          {preview.address}. {preview.bodyLabel}. {preview.nanotons} nanotons.
        </p>
      ) : null}

      <button
        type="button"
        className="ton-button ton-button-quiet"
        onClick={onSend}
        disabled={sendDisabled}
      >
        Send step
      </button>
    </section>
  );
}

function BodyEditor({
  stepId,
  body,
  fieldErrors,
  onChange,
  onField,
  onMoveField,
}: {
  stepId: string;
  body: MessageBody;
  fieldErrors?: Record<string, string>;
  onChange: (body: MessageBody) => void;
  onField: (id: string, field: BodyField) => void;
  onMoveField: (index: number, direction: -1 | 1) => void;
}) {
  if (body.kind === "empty") {
    return <p className="ton-hint">No message body.</p>;
  }

  if (body.kind === "comment") {
    return (
      <textarea
        value={body.text}
        onChange={(event) => onChange({ kind: "comment", text: event.target.value })}
        rows={3}
        placeholder="Text carried in the message"
        aria-label="Comment"
      />
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

  return (
    <div className="ton-fields">
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
      <p className="ton-hint">
        The opcode is stored first as an unsigned integer. Leave it blank to start with the fields.
      </p>
      {body.fields.map((field, index) => (
        <div className="ton-substep" key={field.id}>
          <div className="ton-substep-head">
            <label>
              <span className="ton-mini">Field {index + 1}</span>
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
            </label>
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
          </div>
          <FieldInputs field={field} onField={onField} />
          {fieldErrors?.[field.id] ? (
            <p className="ton-error">{fieldErrors[field.id]}</p>
          ) : null}
        </div>
      ))}
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
    </div>
  );
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
