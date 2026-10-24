import "./buffer-polyfill";
import { Address, beginCell, Cell } from "@ton/core";

/** TON mainnet global id. Testnet is `-3`. */
export const TON_MAINNET_CHAIN = "-239";

const TRANSFER_TTL_SECONDS = 600;
const TEXT_COMMENT_OPCODE = 0;

export type FieldName = "destination" | "amount" | "comment";

export type FieldErrors = Partial<Record<FieldName, string>>;

export type MainnetTransferMessage = {
  address: string;
  amount: string;
  payload?: string;
};

export type MainnetTransferRequest = {
  validUntil: number;
  network: typeof TON_MAINNET_CHAIN;
  from?: string;
  messages: [MainnetTransferMessage];
};

export type TransferValidation =
  | { ok: true; request: MainnetTransferRequest }
  | { ok: false; errors: FieldErrors };

export type SendFailureKind =
  | "cancelled"
  | "wrong-network"
  | "rejected"
  | "manifest"
  | "ambiguous";

export function isMainnetChain(chain: string | null | undefined): boolean {
  return chain === TON_MAINNET_CHAIN;
}

export function chainLabel(chain: string | null | undefined): string {
  if (chain === TON_MAINNET_CHAIN) return "mainnet";
  if (chain === "-3") return "testnet";
  if (!chain) return "an unknown network";
  return `network ${chain}`;
}

export function normalizeMainnetAddress(input: string): string {
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
        bounceable: parsed.isBounceable,
        testOnly: false,
      });
    }

    const address = Address.parse(trimmed);
    return address.toString({
      urlSafe: true,
      bounceable: false,
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

export function validateMainnetTransfer(input: {
  destination: string;
  amountTon: string;
  comment: string;
  fromRaw?: string;
  nowSeconds?: number;
}): TransferValidation {
  const errors: FieldErrors = {};
  let address: string | undefined;
  let amount: string | undefined;
  let payload: string | undefined;
  let commentFailed = false;

  try {
    address = normalizeMainnetAddress(input.destination);
  } catch (error) {
    errors.destination = errorText(error);
  }

  try {
    amount = nanoton(input.amountTon);
  } catch (error) {
    errors.amount = errorText(error);
  }

  try {
    payload = textCommentPayload(input.comment);
  } catch (error) {
    commentFailed = true;
    errors.comment = errorText(error);
  }

  if (!address || !amount || commentFailed) {
    return { ok: false, errors };
  }

  const message: MainnetTransferMessage = { address, amount };
  if (payload) {
    message.payload = payload;
  }

  const request: MainnetTransferRequest = {
    validUntil:
      (input.nowSeconds ?? Math.floor(Date.now() / 1000)) + TRANSFER_TTL_SECONDS,
    network: TON_MAINNET_CHAIN,
    messages: [message],
  };

  const from = senderRaw(input.fromRaw);
  if (from) {
    request.from = from;
  }

  return { ok: true, request };
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
      return "Cancelled in the wallet. The transfer was not sent.";
    case "wrong-network":
      return "This wallet is on another network. Switch it to TON mainnet and connect again. The transfer was not sent.";
    case "rejected":
      return "The wallet rejected the transfer. It was not sent.";
    case "manifest":
      return "The wallet could not read the app manifest. The transfer was not sent.";
    case "ambiguous":
      return "The wallet did not confirm the transfer. Check the wallet before trying again, so the same transfer is not sent twice.";
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

function nanoton(amountTon: string): string {
  const trimmed = amountTon.trim();
  if (!trimmed) {
    throw new Error("Enter an amount in TON.");
  }
  if (!/^\d+(\.\d{1,9})?$/.test(trimmed)) {
    throw new Error("Enter an amount in TON, with up to 9 decimal places.");
  }

  const [whole, frac = ""] = trimmed.split(".");
  const nano =
    BigInt(whole) * BigInt("1000000000") + BigInt(frac.padEnd(9, "0") || "0");
  if (nano <= BigInt(0)) {
    throw new Error("Amount must be greater than zero.");
  }
  return nano.toString();
}

function textCommentPayload(comment: string): string | undefined {
  const trimmed = comment.trim();
  if (!trimmed) return undefined;

  const cell = beginCell()
    .storeUint(TEXT_COMMENT_OPCODE, 32)
    .storeStringTail(trimmed)
    .endCell();

  if (cell.refs.length > 0) {
    throw new Error(
      "That comment is too long for a single message. Shorten it and try again.",
    );
  }

  return cell.toBoc().toString("base64");
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
