import { Address, beginCell } from "@ton/core";
import {
  compileStep,
  normalizeMainnetAddress,
  type BodyField,
  type ScriptStep,
  type StepCompile,
  type StepErrors,
} from "@/lib/ton-message";
import { utonMinter } from "@/lib/uton";
import { UTON_OP } from "@/lib/uton-templates";

/** MINTER::QUERY_FEE. query_data requires msg_value strictly above this. */
export const MINTER_QUERY_FEE_NANOTON = BigInt(10_000_000);

const QUERY_FEE_ERROR = "Attach more than 0.01 TON. The minter requires that on a query.";

/**
 * The body withdraw_ton sends to the minter: opcode 0x1001, the withdraw
 * query id, and a reference holding the recipient and the response address.
 * The minter answers the sender with query_ack. A wallet cannot send
 * query_ack itself; the withdraw contract accepts that opcode only from the minter.
 */
export function compileMinterQuery(withdraw: ScriptStep): StepCompile {
  const fieldErrors: Record<string, string> = {};
  const body =
    withdraw.body.kind === "fields" && withdraw.body.templateId === "withdraw"
      ? withdraw.body
      : undefined;

  if (!body) {
    return {
      ok: false,
      errors: { body: "The withdraw step has to stay a withdraw message." },
    };
  }

  const queryId = readQueryId(body.fields, fieldErrors);
  const recipient = readAddressField(body.fields, "recipient", fieldErrors);
  const response = readAddressField(body.fields, "response", fieldErrors);

  let payload: string | undefined;
  if (queryId !== undefined && recipient && response) {
    const reference = beginCell().storeAddress(recipient).storeAddress(response).endCell();
    payload = beginCell()
      .storeUint(BigInt(UTON_OP.query), 32)
      .storeUint(queryId, 64)
      .storeRef(reference)
      .endCell()
      .toBoc()
      .toString("hex");
  }

  const carrier = compileStep({
    id: "minter-query",
    destination: utonMinter,
    amount: withdraw.amount,
    unit: withdraw.unit,
    bounceable: true,
    body: payload ? { kind: "boc", hex: payload } : { kind: "empty" },
  });

  const errors: StepErrors = {};
  if (Object.keys(fieldErrors).length > 0) errors.fields = fieldErrors;
  if (!carrier.ok) {
    if (carrier.errors.amount) errors.amount = carrier.errors.amount;
    if (carrier.errors.destination) errors.destination = carrier.errors.destination;
    if (!payload && carrier.errors.body) errors.body = carrier.errors.body;
  }

  if (!carrier.ok || !payload || errors.fields) {
    return { ok: false, errors };
  }

  if (BigInt(carrier.message.amount) <= MINTER_QUERY_FEE_NANOTON) {
    return { ok: false, errors: { amount: QUERY_FEE_ERROR } };
  }

  return {
    ok: true,
    message: carrier.message,
    preview: { ...carrier.preview, bodyLabel: "Minter query" },
  };
}

export function minterQueryFailure(errors: StepErrors): string {
  if (errors.amount === QUERY_FEE_ERROR) {
    return `Nothing was sent. ${QUERY_FEE_ERROR}`;
  }
  if (errors.amount) {
    return "Nothing was sent. Enter the TON attached on the withdraw, then try again.";
  }
  if (errors.fields || errors.body) {
    return "Nothing was sent. Complete the withdraw query id, recipient, and response, then try again.";
  }
  return "Nothing was sent. Complete the withdraw, then try again.";
}

function readQueryId(fields: BodyField[], fieldErrors: Record<string, string>): bigint | undefined {
  const field = fields.find((item) => item.id === "query_id");
  if (!field || field.kind !== "uint") {
    fieldErrors.query_id = "This input is missing.";
    return undefined;
  }
  const trimmed = field.value.trim();
  if (!/^0x[0-9a-fA-F]+$/.test(trimmed) && !/^\d+$/.test(trimmed)) {
    fieldErrors.query_id = "Enter a non-negative integer, or 0x hex.";
    return undefined;
  }
  const value = BigInt(trimmed);
  if (value >> BigInt(64) > BigInt(0)) {
    fieldErrors.query_id = "That value does not fit in the bit width.";
    return undefined;
  }
  return value;
}

function readAddressField(
  fields: BodyField[],
  id: string,
  fieldErrors: Record<string, string>,
): Address | undefined {
  const field = fields.find((item) => item.id === id);
  if (!field || field.kind !== "address") {
    fieldErrors[id] = "This input is missing.";
    return undefined;
  }
  try {
    return Address.parse(normalizeMainnetAddress(field.value));
  } catch (error) {
    fieldErrors[id] = error instanceof Error ? error.message : "Enter an address.";
    return undefined;
  }
}
