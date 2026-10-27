/** Display slices for the Katana path. No send handlers. */
export type PathSource = { file: string; code: string };

const claimShares = {
  program: "structured | structuredGeneric",
  instruction: "claim_shares",
  accounts: [
    "state",
    "pricePerSharePage",
    "userAccount",
    "underlyingTokenMint",
    "derivativeTokenMint",
    "derivativeTokenVault",
    "userDerivativeTokenAccount",
    "vaultAuthority",
    "userAuthority",
    "tokenProgram",
  ],
};

const withdrawExpired = {
  program: "structured | structuredGeneric",
  instruction: "withdraw_expired",
  accounts: [
    "state",
    "underlyingTokenMint",
    "underlyingTokenVault",
    "userUnderlyingTokenAccount",
    "derivativeTokenMint",
    "derivativeTokenVault",
    "userDerivativeTokenAccount",
    "pricePerSharePage",
    "userAccount",
    "vaultAuthority",
    "userAuthority",
    "tokenProgram",
  ],
};

const completeWithdraw = {
  instruction: "complete_withdraw",
  accounts: [
    "state",
    "pricePerSharePage",
    "userAccount",
    "underlyingTokenMint",
    "derivativeTokenMint",
    "underlyingTokenVault",
    "derivativeTokenVault",
    "userUnderlyingTokenAccount",
    "vaultAuthority",
    "userAuthority",
    "tokenProgram",
  ],
};

const instantWithdraw = {
  instruction: "instant_withdraw",
  args: { amountUnderlying: "u64" },
  accounts: [
    "state",
    "userAccount",
    "underlyingTokenMint",
    "underlyingTokenVault",
    "userUnderlyingTokenAccount",
    "vaultAuthority",
    "userAuthority",
    "tokenProgram",
  ],
};

const closeUser = {
  instruction: "close_user_account",
  accounts: ["userAccount", "state", "user"],
};

const omitted = [
  "deposit is omitted. An expired vault returns Expired (6028).",
  "migrate is omitted. That path deposited into PsyFi, which shut down on 1 May 2025.",
  "initiate_withdraw is omitted. New withdrawal queues belong to a live round.",
].join("\n");

export const katanaPathSource = {
  claimShares: {
    file: "Katana · claim_shares",
    code: JSON.stringify(claimShares, null, 2),
  },
  withdrawExpired: {
    file: "Katana · withdraw_expired",
    code: JSON.stringify(withdrawExpired, null, 2),
  },
  completeWithdraw: {
    file: "Katana · complete_withdraw",
    code: JSON.stringify(completeWithdraw, null, 2),
  },
  instantWithdraw: {
    file: "Katana · instant_withdraw",
    code: JSON.stringify(instantWithdraw, null, 2),
  },
  closeUser: {
    file: "Katana · close_user_account",
    code: JSON.stringify(closeUser, null, 2),
  },
  omitted: {
    file: "Katana · not sent",
    code: omitted,
  },
} as const satisfies Record<string, PathSource>;
