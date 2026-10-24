/**
 * User-facing message shapes from UTONICFinance/utonic-contracts-uTON @ b92e674.
 * Opcodes are the ones the FunC parsers load. Stake is 0x1003 in
 * common_op.func; the TL-B sketch writes stake#00001000.
 */

export const UTON_OP = {
  burn: "0x595f07bc",
  burnNotification: "0x7bdd97de",
  withdraw: "0x4502",
  stake: "0x1003",
  transfer: "0x0f8a7ea5",
} as const;

/** Starting nanotons for a burn's forward value. This is MINTER::BURN_FEE in the source. The wallet only requires a value above zero. */
export const UTON_BURN_FORWARD_START = "10000000";

export type UtonTemplateId =
  | "uton-burn"
  | "burn-notification"
  | "withdraw"
  | "stake-ton"
  | "jetton-transfer";

export type UtonTemplateField =
  | { id: string; label: string; kind: "uint"; bits: string; value: string }
  | { id: string; label: string; kind: "coins" | "address" | "text"; value: string };

export type UtonTemplate = {
  id: UtonTemplateId;
  label: string;
  detail: string;
  destinationHint: string;
  valueHint: string;
  bounceable: boolean;
  opcode: string;
  opcodeBits: string;
  fields: readonly UtonTemplateField[];
};

const queryId: UtonTemplateField = {
  id: "query_id",
  label: "Query id",
  kind: "uint",
  bits: "64",
  value: "0",
};

export const utonTemplates: readonly UtonTemplate[] = [
  {
    id: "uton-burn",
    label: "uTON burn",
    detail:
      "Burn on your uTON wallet. Opcode 0x595f07bc. The custom payload is a dictionary: key 0 holds the proxy id, the forward value, and an empty forward cell. That cell is not editable here.",
    destinationHint: "Paste your uTON wallet.",
    valueHint: "TON attached to this message. The uTON amount is a field below.",
    bounceable: true,
    opcode: UTON_OP.burn,
    opcodeBits: "32",
    fields: [
      queryId,
      { id: "amount", label: "uTON amount", kind: "coins", value: "" },
      { id: "response", label: "Response address", kind: "address", value: "" },
      { id: "proxy_id", label: "Proxy id", kind: "uint", bits: "32", value: "0" },
      {
        id: "fwd_value",
        label: "Forward value",
        kind: "coins",
        value: UTON_BURN_FORWARD_START,
      },
    ],
  },
  {
    id: "burn-notification",
    label: "Burn notification",
    detail:
      "The body the wallet sends on to the minter. Opcode 0x7bdd97de. The owner address is stored before the uTON amount. An empty forward cell is attached as a reference and is not editable here.",
    destinationHint: "Paste the minter. The wallet normally sends this itself.",
    valueHint: "TON attached to this message.",
    bounceable: true,
    opcode: UTON_OP.burnNotification,
    opcodeBits: "32",
    fields: [
      queryId,
      { id: "owner", label: "Owner", kind: "address", value: "" },
      { id: "withdraw_id", label: "Withdraw id", kind: "uint", bits: "64", value: "0" },
      { id: "amount", label: "uTON amount", kind: "coins", value: "" },
      { id: "proxy_id", label: "Proxy id", kind: "uint", bits: "32", value: "0" },
      { id: "response", label: "Response address", kind: "address", value: "" },
      {
        id: "fwd_value",
        label: "Forward value",
        kind: "coins",
        value: UTON_BURN_FORWARD_START,
      },
    ],
  },
  {
    id: "withdraw",
    label: "Withdraw",
    detail:
      "Withdraw on the pending withdraw contract, after its time lock. Opcode 0x4502. The recipient receives the TON. The response address receives excess gas.",
    destinationHint: "Paste the pending withdraw contract.",
    valueHint: "TON attached for gas. The withdrawn TON is paid by the proxy.",
    bounceable: true,
    opcode: UTON_OP.withdraw,
    opcodeBits: "32",
    fields: [
      queryId,
      { id: "recipient", label: "Recipient", kind: "address", value: "" },
      { id: "response", label: "Response address", kind: "address", value: "" },
    ],
  },
  {
    id: "stake-ton",
    label: "Stake native TON",
    detail:
      "Stake on proxy_ton. The contract reads opcode 0x1003. The TL-B sketch writes stake as 0x1000.",
    destinationHint: "Paste the proxy_ton address.",
    valueHint: "TON deposited with this message. The proxy takes its fees from it.",
    bounceable: true,
    opcode: UTON_OP.stake,
    opcodeBits: "32",
    fields: [
      queryId,
      { id: "user", label: "User address", kind: "address", value: "" },
      { id: "response", label: "Response address", kind: "address", value: "" },
    ],
  },
  {
    id: "jetton-transfer",
    label: "uTON transfer",
    detail:
      "Transfer on your uTON wallet. Opcode 0x0f8a7ea5. The custom payload is empty. Leave forward text blank for an inline empty payload.",
    destinationHint: "Paste your uTON wallet.",
    valueHint: "TON attached to this message. Forward TON is a field below.",
    bounceable: true,
    opcode: UTON_OP.transfer,
    opcodeBits: "32",
    fields: [
      queryId,
      { id: "amount", label: "uTON amount", kind: "coins", value: "" },
      { id: "destination", label: "Jetton destination", kind: "address", value: "" },
      { id: "response", label: "Response address", kind: "address", value: "" },
      { id: "forward_ton", label: "Forward TON", kind: "coins", value: "0" },
      { id: "forward_text", label: "Forward text", kind: "text", value: "" },
    ],
  },
];

export function utonTemplateById(id: string | undefined): UtonTemplate | undefined {
  return utonTemplates.find((template) => template.id === id);
}

export function utonTemplateBody(template: UtonTemplate): {
  kind: "fields";
  templateId: UtonTemplateId;
  opcode: string;
  opcodeBits: string;
  fields: UtonTemplateField[];
} {
  return {
    kind: "fields",
    templateId: template.id,
    opcode: template.opcode,
    opcodeBits: template.opcodeBits,
    fields: template.fields.map((field) =>
      field.kind === "uint"
        ? { ...field }
        : { id: field.id, label: field.label, kind: field.kind, value: field.value },
    ),
  };
}

export function templatePreviewLabel(
  templateId: string,
  fields: readonly { id: string; value: string }[],
): string {
  const name = utonTemplateById(templateId)?.label ?? "Known message";
  if (templateId === "uton-burn" || templateId === "burn-notification") {
    const proxy = fields.find((field) => field.id === "proxy_id")?.value.trim() || "—";
    return `${name} · proxy_id ${proxy}`;
  }
  return name;
}
