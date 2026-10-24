import "./buffer-polyfill";
import { Address, beginCell, Cell, Dictionary, type Builder } from "@ton/core";
import { templatePreviewLabel, utonTemplateById } from "./uton-templates";

/** TON mainnet global id. Testnet is `-3`. */
export const TON_MAINNET_CHAIN = "-239";

const TRANSFER_TTL_SECONDS = 600;
const TEXT_COMMENT_OPCODE = 0;
const UNADVERTISED_MAX_MESSAGES = 4;

export type AmountUnit = "ton" | "nanoton";

export type BodyField =
  | { id: string; kind: "uint"; bits: string; value: string; label?: string }
  | { id: string; kind: "coins"; value: string; label?: string }
  | { id: string; kind: "address"; value: string; label?: string }
  | { id: string; kind: "text"; value: string; label?: string };

export type MessageBody =
  | { kind: "empty" }
  | { kind: "comment"; text: string }
  | { kind: "boc"; hex: string }
  | {
      kind: "fields";
      opcode: string;
      opcodeBits: string;
      fields: BodyField[];
      templateId?: string;
    };

export type ScriptStep = {
  id: string;
  destination: string;
  amount: string;
  unit: AmountUnit;
  bounceable: boolean;
  body: MessageBody;
};

export type StepErrors = {
  destination?: string;
  amount?: string;
  body?: string;
  fields?: Record<string, string>;
};

export type OutgoingMessage = {
  address: string;
  amount: string;
  payload?: string;
};

export type MainnetScriptRequest = {
  validUntil: number;
  network: typeof TON_MAINNET_CHAIN;
  from?: string;
  messages: OutgoingMessage[];
};

export type StepPreview = {
  address: string;
  bounceable: boolean;
  nanotons: string;
  valueLabel: string;
  bodyLabel: string;
};

export type StepCompile =
  | { ok: true; message: OutgoingMessage; preview: StepPreview }
  | { ok: false; errors: StepErrors };

export type ScriptCompile =
  | { ok: true; request: MainnetScriptRequest; previews: StepPreview[] }
  | { ok: false; steps: Array<StepErrors | undefined>; message?: string };

export type SendFailureKind =
  | "cancelled"
  | "wrong-network"
  | "rejected"
  | "manifest"
  | "ambiguous";

export type WalletMessageLimit = {
  maxMessages: number;
  advertised: boolean;
};

export function emptyStep(id: string): ScriptStep {
  return {
    id,
    destination: "",
    amount: "",
    unit: "ton",
    bounceable: true,
    body: { kind: "empty" },
  };
}

export function isMainnetChain(chain: string | null | undefined): boolean {
  return chain === TON_MAINNET_CHAIN;
}

export function chainLabel(chain: string | null | undefined): string {
  if (chain === TON_MAINNET_CHAIN) return "mainnet";
  if (chain === "-3") return "testnet";
  if (!chain) return "an unknown network";
  return `network ${chain}`;
}

export function readMaxMessages(
  features: readonly unknown[] | null | undefined,
): WalletMessageLimit | null {
  if (!features) return null;

  for (const feature of features) {
    if (!feature || typeof feature !== "object" || !("name" in feature)) continue;
    if (feature.name !== "SendTransaction" || !("maxMessages" in feature)) continue;
    const maxMessages = feature.maxMessages;
    if (
      typeof maxMessages === "number" &&
      Number.isInteger(maxMessages) &&
      maxMessages >= 1
    ) {
      return { maxMessages, advertised: true };
    }
  }

  if (features.some((feature) => feature === "SendTransaction")) {
    return { maxMessages: UNADVERTISED_MAX_MESSAGES, advertised: false };
  }

  return { maxMessages: 1, advertised: false };
}

export function normalizeMainnetAddress(
  input: string,
  bounceable?: boolean,
): string {
  const trimmed = input.trim();
  if (!trimmed) {
    throw new Error("Enter a destination address.");
  }

  try {
    if (Address.isFriendly(trimmed)) {
      const parsed = Address.parseFriendly(trimmed);
      if (parsed.isTestOnly) {
        throw new Error(
          "That address is marked for testnet. Use a mainnet address.",
        );
      }
      return parsed.address.toString({
        urlSafe: true,
        bounceable: bounceable ?? parsed.isBounceable,
        testOnly: false,
      });
    }

    const address = Address.parse(trimmed);
    return address.toString({
      urlSafe: true,
      bounceable: bounceable ?? false,
      testOnly: false,
    });
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("That address")) {
      throw error;
    }
    throw new Error(
      "That address could not be read. Paste a mainnet TON address.",
    );
  }
}

export function compileStep(step: ScriptStep): StepCompile {
  const errors: StepErrors = {};
  let address: string | undefined;
  let amount: string | undefined;
  let payload: string | undefined;
  let bodyLabel = "Empty body";
  let bodyFailed = false;

  try {
    address = normalizeMainnetAddress(step.destination, step.bounceable);
  } catch (error) {
    errors.destination = errorText(error);
  }

  try {
    amount = amountToNanoton(step.amount, step.unit);
  } catch (error) {
    errors.amount = errorText(error);
  }

  try {
    const body = buildBody(step.body);
    if (body.fieldErrors && Object.keys(body.fieldErrors).length > 0) {
      errors.fields = body.fieldErrors;
      bodyFailed = true;
    } else {
      payload = body.payload;
      bodyLabel = body.label;
    }
  } catch (error) {
    errors.body = errorText(error);
    bodyFailed = true;
  }

  if (!address || amount === undefined || bodyFailed) {
    return { ok: false, errors };
  }

  const message: OutgoingMessage = { address, amount };
  if (payload) message.payload = payload;

  return {
    ok: true,
    message,
    preview: {
      address,
      bounceable: step.bounceable,
      nanotons: amount,
      valueLabel: valueLabel(step, amount),
      bodyLabel,
    },
  };
}

export function addNanotons(values: readonly string[]): string {
  let sum = BigInt(0);
  for (const value of values) {
    if (!/^\d+$/.test(value)) {
      throw new Error("Nanoton totals are whole numbers.");
    }
    sum += BigInt(value);
  }
  return sum.toString();
}

export function formatNanotons(nanotons: string): string {
  if (!/^\d+$/.test(nanotons)) {
    throw new Error("Nanoton totals are whole numbers.");
  }
  const value = BigInt(nanotons);
  const scale = BigInt("1000000000");
  const whole = value / scale;
  const fraction = (value % scale).toString().padStart(9, "0").replace(/0+$/, "");
  const amount = fraction ? `${whole.toString()}.${fraction}` : whole.toString();
  return `${amount} TON`;
}

export function scriptValueSummary(compiled: readonly StepCompile[]): string {
  const count = compiled.length;
  if (count === 0) return "No messages in this script.";

  const ready = compiled.flatMap((item) => (item.ok ? [item.preview.nanotons] : []));
  if (ready.length === 0) {
    return count === 1
      ? "1 message. Complete it to see a total."
      : `${count} messages. Complete them to see a total.`;
  }

  const total = formatNanotons(addNanotons(ready));
  if (ready.length === count) {
    const noun = count === 1 ? "message" : "messages";
    return `${count} ${noun} · ${total} in this script.`;
  }
  return `${ready.length} of ${count} steps compile · ${total} so far.`;
}

export function compileScript(
  steps: ScriptStep[],
  options?: {
    fromRaw?: string;
    nowSeconds?: number;
    maxMessages?: number;
  },
): ScriptCompile {
  if (steps.length === 0) {
    return { ok: false, steps: [], message: "Add a message." };
  }

  const compiled = steps.map((step) => compileStep(step));
  const stepErrors = compiled.map((item) => (item.ok ? undefined : item.errors));
  const limitMessage =
    options?.maxMessages !== undefined && steps.length > options.maxMessages
      ? limitText(options.maxMessages, steps.length)
      : undefined;

  if (compiled.some((item) => !item.ok) || limitMessage) {
    return { ok: false, steps: stepErrors, message: limitMessage };
  }

  const messages: OutgoingMessage[] = [];
  const previews: StepPreview[] = [];
  for (const item of compiled) {
    if (!item.ok) return { ok: false, steps: stepErrors, message: limitMessage };
    messages.push(item.message);
    previews.push(item.preview);
  }

  const request: MainnetScriptRequest = {
    validUntil:
      (options?.nowSeconds ?? Math.floor(Date.now() / 1000)) + TRANSFER_TTL_SECONDS,
    network: TON_MAINNET_CHAIN,
    messages,
  };
  const from = senderRaw(options?.fromRaw);
  if (from) request.from = from;

  return { ok: true, request, previews };
}

export function classifySendError(error: unknown): SendFailureKind {
  const name = readName(error);
  const code = readWalletErrorCode(error);

  if (name === "WalletWrongNetworkError") return "wrong-network";
  if (name === "UserRejectsError" || code === 300) return "cancelled";
  if (
    name === "ManifestNotFoundError" ||
    name === "ManifestContentErrorError" ||
    code === 2 ||
    code === 3
  ) {
    return "manifest";
  }
  if (
    name === "BadRequestError" ||
    name === "UnknownAppError" ||
    name === "MethodNotSupportedError" ||
    name === "WalletNotSupportFeatureError" ||
    code === 1 ||
    code === 100 ||
    code === 400
  ) {
    return "rejected";
  }
  return "ambiguous";
}

export function sendFailureMessage(kind: SendFailureKind): string {
  switch (kind) {
    case "cancelled":
      return "Cancelled in the wallet. Nothing was sent.";
    case "wrong-network":
      return "This wallet is on another network. Switch it to TON mainnet and connect again. Nothing was sent.";
    case "rejected":
      return "The wallet rejected the message. Nothing was sent.";
    case "manifest":
      return "The wallet could not read the app manifest. Nothing was sent.";
    case "ambiguous":
      return "The wallet did not confirm the message. Check the wallet before trying again, so it is not sent twice.";
  }
}

export function connectFailureMessage(
  kind: SendFailureKind,
  manifestUrl: string,
): string | null {
  switch (kind) {
    case "cancelled":
      return null;
    case "wrong-network":
      return "This wallet is on another network. Switch it to TON mainnet and connect again.";
    case "manifest":
      return `The wallet could not read the app manifest at ${manifestUrl}.`;
    case "rejected":
    case "ambiguous":
      return "The wallet did not connect.";
  }
}

export function decodeTextComment(payload: string): string {
  const slice = Cell.fromBase64(payload).beginParse();
  const opcode = slice.loadUint(32);
  if (opcode !== TEXT_COMMENT_OPCODE) {
    throw new Error("Payload is not a text comment.");
  }
  return slice.loadStringTail();
}

function buildBody(body: MessageBody): {
  payload?: string;
  label: string;
  fieldErrors?: Record<string, string>;
} {
  if (body.kind === "empty") {
    return { label: "Empty body" };
  }
  if (body.kind === "comment") return buildComment(body.text);
  if (body.kind === "boc") return buildBoc(body.hex);
  return buildFields(body);
}

function buildComment(text: string): { payload: string; label: string } {
  const trimmed = text.trim();
  if (!trimmed) throw new Error("Enter a comment.");

  const cell = beginCell()
    .storeUint(TEXT_COMMENT_OPCODE, 32)
    .storeStringTail(trimmed)
    .endCell();
  if (cell.refs.length > 0) {
    throw new Error(
      "That comment is too long for a single message. Shorten it and try again.",
    );
  }

  const shown = trimmed.length > 48 ? `${trimmed.slice(0, 48)}…` : trimmed;
  return {
    payload: cell.toBoc().toString("base64"),
    label: `Text comment “${shown}”`,
  };
}

function buildBoc(hex: string): { payload: string; label: string } {
  const cell = parseBoc(hex);
  const refs =
    cell.refs.length > 0
      ? `, ${cell.refs.length} ${cell.refs.length === 1 ? "ref" : "refs"}`
      : "";
  return {
    payload: cell.toBoc().toString("base64"),
    label: `BoC cell, ${cell.bits.length} bits${refs}`,
  };
}

function parseBoc(input: string): Cell {
  const compact = input.trim().replace(/\s+/g, "");
  if (!compact) throw new Error("Paste a BoC.");

  const bare = compact.replace(/^0x/i, "");
  if (/^[0-9a-fA-F]+$/.test(bare) && bare.length % 2 === 0) {
    try {
      return Cell.fromHex(bare);
    } catch {
      throw new Error("That hex is not a single-root BoC.");
    }
  }

  try {
    return Cell.fromBase64(compact);
  } catch {
    throw new Error("Paste a hex BoC, or a base64 BoC of one cell.");
  }
}

function buildFields(body: Extract<MessageBody, { kind: "fields" }>): {
  payload?: string;
  label: string;
  fieldErrors?: Record<string, string>;
} {
  if (body.templateId) return buildUtonTemplate(body);

  const fieldErrors: Record<string, string> = {};
  const builder = beginCell();
  const opcode = body.opcode.trim();

  if (!opcode && body.fields.length === 0) {
    throw new Error("Add an opcode or a field.");
  }

  if (opcode) {
    const bits = parseBitWidth(body.opcodeBits);
    const value = parseUnsigned(opcode, "Enter an opcode as an integer or 0x hex.");
    if (!fitsUnsigned(value, bits)) {
      throw new Error("The opcode does not fit in that bit width.");
    }
    builder.storeUint(value, bits);
  }

  body.fields.forEach((field, index) => {
    if (field.kind === "text" && index !== body.fields.length - 1) {
      fieldErrors[field.id] = "A text tail has to be the last field.";
    }
  });
  if (Object.keys(fieldErrors).length > 0) {
    return { label: "", fieldErrors };
  }

  for (const field of body.fields) {
    try {
      storeField(builder, field);
    } catch (error) {
      fieldErrors[field.id] = errorText(error);
    }
  }
  if (Object.keys(fieldErrors).length > 0) {
    return { label: "", fieldErrors };
  }

  let cell: Cell;
  try {
    cell = builder.endCell();
  } catch (error) {
    throw new Error(errorText(error));
  }
  if (cell.refs.length > 0) {
    throw new Error(
      "That body does not fit in one cell. Shorten it and try again.",
    );
  }

  const opcodeLabel = opcode ? `Opcode ${formatInteger(opcode)}, ` : "";
  const count = body.fields.length;
  return {
    payload: cell.toBoc().toString("base64"),
    label: `${opcodeLabel}${count} ${count === 1 ? "field" : "fields"}, ${cell.bits.length} bits`,
  };
}

function buildUtonTemplate(body: Extract<MessageBody, { kind: "fields" }>): {
  payload?: string;
  label: string;
  fieldErrors?: Record<string, string>;
} {
  const templateId = body.templateId ?? "";
  if (!utonTemplateById(templateId)) {
    throw new Error("Unknown message template.");
  }

  const fieldErrors: Record<string, string> = {};
  const builder = beginCell();

  try {
    storeOpcode(builder, body);
  } catch (error) {
    throw new Error(errorText(error));
  }

  const uintAt = (id: string) => {
    const field = requireField(body.fields, id, fieldErrors);
    if (!field) return undefined;
    if (field.kind !== "uint") {
      fieldErrors[id] = "Expected an unsigned integer.";
      return undefined;
    }
    try {
      const parsed = readUint(field);
      builder.storeUint(parsed.value, parsed.bits);
      return parsed;
    } catch (error) {
      fieldErrors[id] = errorText(error);
      return undefined;
    }
  };
  const coinsAt = (id: string) => {
    const field = requireField(body.fields, id, fieldErrors);
    if (!field) return undefined;
    if (field.kind !== "coins") {
      fieldErrors[id] = "Expected a coin amount.";
      return undefined;
    }
    try {
      const value = readCoins(field);
      builder.storeCoins(value);
      return value;
    } catch (error) {
      fieldErrors[id] = errorText(error);
      return undefined;
    }
  };
  const addressAt = (id: string) => {
    const field = requireField(body.fields, id, fieldErrors);
    if (!field) return undefined;
    if (field.kind !== "address") {
      fieldErrors[id] = "Expected an address.";
      return undefined;
    }
    try {
      const address = readAddress(field);
      builder.storeAddress(address);
      return address;
    } catch (error) {
      fieldErrors[id] = errorText(error);
      return undefined;
    }
  };

  if (templateId === "uton-burn") {
    uintAt("query_id");
    coinsAt("amount");
    addressAt("response");
    const proxy = readOptionalUint(body.fields, "proxy_id", fieldErrors);
    const forward = readOptionalCoins(body.fields, "fwd_value", fieldErrors);
    if (Object.keys(fieldErrors).length > 0) return { label: "", fieldErrors };
    if (proxy === undefined || forward === undefined) return { label: "", fieldErrors };
    const payload = beginCell()
      .storeUint(proxy.value, proxy.bits)
      .storeCoins(forward)
      .storeRef(beginCell().endCell())
      .endCell();
    const dictionary = Dictionary.empty(
      Dictionary.Keys.Uint(32),
      Dictionary.Values.Cell(),
    );
    dictionary.set(0, payload);
    builder.storeDict(dictionary);
  } else if (templateId === "burn-notification") {
    uintAt("query_id");
    addressAt("owner");
    uintAt("withdraw_id");
    coinsAt("amount");
    uintAt("proxy_id");
    addressAt("response");
    coinsAt("fwd_value");
    if (Object.keys(fieldErrors).length > 0) return { label: "", fieldErrors };
    builder.storeRef(beginCell().endCell());
  } else if (templateId === "withdraw") {
    uintAt("query_id");
    addressAt("recipient");
    addressAt("response");
    if (Object.keys(fieldErrors).length > 0) return { label: "", fieldErrors };
  } else if (templateId === "stake-ton") {
    uintAt("query_id");
    addressAt("user");
    addressAt("response");
    if (Object.keys(fieldErrors).length > 0) return { label: "", fieldErrors };
  } else if (templateId === "jetton-transfer") {
    uintAt("query_id");
    coinsAt("amount");
    addressAt("destination");
    addressAt("response");
    if (Object.keys(fieldErrors).length > 0) return { label: "", fieldErrors };
    builder.storeMaybeRef(null);
    coinsAt("forward_ton");
    const textField = requireField(body.fields, "forward_text", fieldErrors);
    if (textField && textField.kind !== "text" && !fieldErrors.forward_text) {
      fieldErrors.forward_text = "Expected text.";
    }
    if (Object.keys(fieldErrors).length > 0) return { label: "", fieldErrors };
    const text = textField && textField.kind === "text" ? textField.value.trim() : "";
    if (!text) {
      builder.storeBit(0);
    } else {
      builder.storeBit(1).storeRef(beginCell().storeStringTail(text).endCell());
    }
  } else {
    throw new Error("Unknown message template.");
  }

  let cell: Cell;
  try {
    cell = builder.endCell();
  } catch (error) {
    throw new Error(errorText(error));
  }

  return {
    payload: cell.toBoc().toString("base64"),
    label: templatePreviewLabel(templateId, body.fields),
  };
}

function requireField(
  fields: BodyField[],
  id: string,
  fieldErrors: Record<string, string>,
): BodyField | undefined {
  const field = fields.find((item) => item.id === id);
  if (!field) {
    fieldErrors[id] = "This input is missing.";
    return undefined;
  }
  return field;
}

function readOptionalUint(
  fields: BodyField[],
  id: string,
  fieldErrors: Record<string, string>,
): { value: bigint; bits: number } | undefined {
  const field = requireField(fields, id, fieldErrors);
  if (!field) return undefined;
  if (field.kind !== "uint") {
    fieldErrors[id] = "Expected an unsigned integer.";
    return undefined;
  }
  try {
    return readUint(field);
  } catch (error) {
    fieldErrors[id] = errorText(error);
    return undefined;
  }
}

function readOptionalCoins(
  fields: BodyField[],
  id: string,
  fieldErrors: Record<string, string>,
): bigint | undefined {
  const field = requireField(fields, id, fieldErrors);
  if (!field) return undefined;
  if (field.kind !== "coins") {
    fieldErrors[id] = "Expected a coin amount.";
    return undefined;
  }
  try {
    return readCoins(field);
  } catch (error) {
    fieldErrors[id] = errorText(error);
    return undefined;
  }
}

function readUint(field: Extract<BodyField, { kind: "uint" }>): {
  value: bigint;
  bits: number;
} {
  const bits = parseBitWidth(field.bits);
  const value = parseUnsigned(field.value, "Enter a non-negative integer, or 0x hex.");
  if (!fitsUnsigned(value, bits)) {
    throw new Error("That value does not fit in the bit width.");
  }
  return { value, bits };
}

function readCoins(field: Extract<BodyField, { kind: "coins" }>): bigint {
  return parseUnsigned(field.value, "Enter a whole number of nanotons.");
}

function readAddress(field: Extract<BodyField, { kind: "address" }>): Address {
  if (!field.value.trim()) throw new Error("Enter an address.");
  return Address.parse(normalizeMainnetAddress(field.value));
}

function storeOpcode(builder: Builder, body: Extract<MessageBody, { kind: "fields" }>) {
  const opcode = body.opcode.trim();
  if (!opcode) throw new Error("Enter an opcode.");
  const bits = parseBitWidth(body.opcodeBits);
  const value = parseUnsigned(opcode, "Enter an opcode as an integer or 0x hex.");
  if (!fitsUnsigned(value, bits)) {
    throw new Error("The opcode does not fit in that bit width.");
  }
  builder.storeUint(value, bits);
}

function storeField(builder: Builder, field: BodyField) {
  if (field.kind === "uint") {
    const bits = parseBitWidth(field.bits);
    const value = parseUnsigned(field.value, "Enter a non-negative integer, or 0x hex.");
    if (!fitsUnsigned(value, bits)) {
      throw new Error("That value does not fit in the bit width.");
    }
    builder.storeUint(value, bits);
    return;
  }

  if (field.kind === "coins") {
    const value = parseUnsigned(field.value, "Enter a whole number of nanotons.");
    builder.storeCoins(value);
    return;
  }

  if (field.kind === "address") {
    const friendly = normalizeMainnetAddress(field.value);
    builder.storeAddress(Address.parse(friendly));
    return;
  }

  const text = field.value.trim();
  if (!text) throw new Error("Enter the text tail.");
  builder.storeStringTail(text);
}

function amountToNanoton(amount: string, unit: AmountUnit): string {
  const trimmed = amount.trim();
  if (!trimmed) throw new Error("Enter a value.");

  if (unit === "nanoton") {
    if (!/^\d+$/.test(trimmed)) {
      throw new Error("Enter a whole number of nanotons.");
    }
    return BigInt(trimmed).toString();
  }

  if (!/^\d+(\.\d{1,9})?$/.test(trimmed)) {
    throw new Error("Enter a TON amount with up to 9 decimal places.");
  }

  const [whole, frac = ""] = trimmed.split(".");
  const nano =
    BigInt(whole) * BigInt("1000000000") + BigInt(frac.padEnd(9, "0") || "0");
  return nano.toString();
}

function valueLabel(step: ScriptStep, nanotons: string): string {
  if (step.unit === "nanoton") return `${nanotons} nanotons`;
  return `${step.amount.trim()} TON`;
}

function parseBitWidth(input: string): number {
  const trimmed = input.trim();
  if (!/^\d+$/.test(trimmed)) {
    throw new Error("Enter a bit width from 1 to 256.");
  }
  const bits = Number(trimmed);
  if (!Number.isInteger(bits) || bits < 1 || bits > 256) {
    throw new Error("Enter a bit width from 1 to 256.");
  }
  return bits;
}

function parseUnsigned(input: string, message: string): bigint {
  const trimmed = input.trim();
  if (/^0x[0-9a-fA-F]+$/.test(trimmed) || /^\d+$/.test(trimmed)) {
    return BigInt(trimmed);
  }
  throw new Error(message);
}

function fitsUnsigned(value: bigint, bits: number): boolean {
  if (value < BigInt(0)) return false;
  if (value === BigInt(0)) return bits >= 1;
  return value.toString(2).length <= bits;
}

function formatInteger(input: string): string {
  const value = parseUnsigned(input, "");
  return `0x${value.toString(16)}`;
}

function limitText(maxMessages: number, count: number): string {
  const noun = maxMessages === 1 ? "message" : "messages";
  return `This wallet accepts ${maxMessages} ${noun} per confirmation. This script has ${count}. Send a step on its own, or shorten the script.`;
}

function senderRaw(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  if (!trimmed || !Address.isRaw(trimmed)) return undefined;
  try {
    return Address.parseRaw(trimmed).toRawString();
  } catch {
    return undefined;
  }
}

function errorText(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "Check this field and try again.";
}

function readName(error: unknown): string {
  if (typeof error === "object" && error !== null && "name" in error) {
    return String(error.name);
  }
  return "";
}

function readWalletErrorCode(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null || !("walletError" in error)) {
    return undefined;
  }
  const walletError = error.walletError;
  if (
    typeof walletError === "object" &&
    walletError !== null &&
    "code" in walletError &&
    typeof walletError.code === "number"
  ) {
    return walletError.code;
  }
  return undefined;
}
