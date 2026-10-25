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
    msg: { withdraw_unbonded_by_id: { id: 12 } },
    funds: [],
  },
};

const handler = [
  "1. Read paused. Stop when paused is true (StdContractPaused).",
  "2. Read completed_unbondings[id]: id, withdrawal_id, address, amount, timestamp.",
  "3. Missing id → CompletedUnbondingNotFound.",
  "4. Sender must equal the stored address, otherwise UnauthorizedWithdrawal.",
  "5. Remove completed_unbondings[id] and the withdrawal_to_completed_unbonding link.",
  "6. Subtract amount from total_completed_unbonding_amount and unbonded_withdrawal_reserve.",
  "7. Decrement total_completed_unbonding_count.",
  "8. Bank-send azig of the stored amount to the stored address.",
  "9. Emit wasm method withdraw_unbonded_by_id.",
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
