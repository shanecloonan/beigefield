/** Display slices for the Valdora path. No send handlers. */
export type PathSource = { file: string; code: string };

const queryTotals = {
  total_completed_unbondings: {},
};

const queryTotalsSample = {
  data: {
    total_count: 54,
    total_amount: "17549100531498156676062279",
  },
};

const executeMsg = {
  typeUrl: "/cosmwasm.wasm.v1.MsgExecuteContract",
  value: {
    sender: "<desk zig1>",
    contract: "zig18nnde5tpn76xj3wm53n0tmuf3q06nruj3p6kdemcllzxqwzkpqzqk7ue55",
    msg: { withdraw_unbonded_by_id: { withdrawal_request_id: 12 } },
    funds: [],
  },
};

const handler = [
  "1. Load withdrawal_to_completed_unbonding for the supplied id.",
  "2. Load that completed record. A missing id is not found.",
  "3. Do not compare the signer to the address on the record.",
  "4. Decrement total_completed_unbonding_amount and total_completed_unbonding_count.",
  "5. Remove the mapping entry and the completed-unbonding record.",
  "6. Bank-send azig to the transaction signer.",
  "7. Emit wasm attributes with sender set to the transaction signer.",
  "The address-scoped error belongs to withdraw_unbonded, which takes no id.",
  "A live by-id execute on code id 179 still returns No completed unbondings found for address for this desk, including 327. That simulation is rejected and nothing is broadcast.",
].join("\n");

export const valdoraPathSource = {
  queryTotals: {
    file: "lcd smart query · total_completed_unbondings",
    code: JSON.stringify(queryTotals, null, 2),
  },
  queryTotalsSample: {
    file: "lcd response sample",
    code: JSON.stringify(queryTotalsSample, null, 2),
  },
  queryPaused: {
    file: "lcd smart query · paused",
    code: JSON.stringify({ paused: {} }, null, 2),
  },
  queryProtocol: {
    file: "lcd smart query · protocol_info",
    code: JSON.stringify({ protocol_info: {} }, null, 2),
  },
  execute: {
    file: "MsgExecuteContract",
    code: JSON.stringify(executeMsg, null, 2),
  },
  handler: {
    file: "stzig-staker 1.1.0 · withdraw_unbonded_by_id",
    code: handler,
  },
} as const satisfies Record<string, PathSource>;
