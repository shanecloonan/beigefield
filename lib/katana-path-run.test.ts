import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { DEFAULT_KATANA_VAULT } from "./katana";
import {
  compilePathRun,
  pathLookupNote,
  readKatanaPathDefaults,
  readKatanaSendResult,
  suggestKatanaAction,
} from "./katana-path-run";
import { SOL_FUNDED_WALLET_ADDRESS } from "./sol-funded-wallet-public";

describe("compilePathRun", () => {
  it("builds a Katana exit on the default SOL covered-call vault", () => {
    const compiled = compilePathRun({
      sender: SOL_FUNDED_WALLET_ADDRESS,
      state: DEFAULT_KATANA_VAULT,
      action: "exit",
    });
    assert.equal(compiled.ok, true);
    if (!compiled.ok) return;
    assert.equal(compiled.action, "exit");
    assert.equal(compiled.state, DEFAULT_KATANA_VAULT);
    assert.equal(compiled.sender, SOL_FUNDED_WALLET_ADDRESS);
    assert.match(compiled.summary, /exit on SOL Covered call/);
  });

  it("requires amount_underlying only for instant_withdraw", () => {
    const missing = compilePathRun({
      sender: SOL_FUNDED_WALLET_ADDRESS,
      state: DEFAULT_KATANA_VAULT,
      action: "instant_withdraw",
    });
    assert.equal(missing.ok, false);

    const extra = compilePathRun({
      sender: SOL_FUNDED_WALLET_ADDRESS,
      state: DEFAULT_KATANA_VAULT,
      action: "exit",
      amount: "1",
    });
    assert.equal(extra.ok, false);

    const ok = compilePathRun({
      sender: SOL_FUNDED_WALLET_ADDRESS,
      state: DEFAULT_KATANA_VAULT,
      action: "instant_withdraw",
      amount: "1000",
    });
    assert.equal(ok.ok, true);
    if (ok.ok) assert.equal(ok.amount, "1000");
  });

  it("rejects a missing vault, a bad sender, and a deposit", () => {
    assert.equal(
      compilePathRun({
        sender: "not-an-address",
        state: DEFAULT_KATANA_VAULT,
        action: "exit",
      }).ok,
      false,
    );
    assert.equal(
      compilePathRun({
        sender: SOL_FUNDED_WALLET_ADDRESS,
        state: "11111111111111111111111111111111",
        action: "exit",
      }).ok,
      false,
    );
    assert.equal(
      compilePathRun({
        sender: SOL_FUNDED_WALLET_ADDRESS,
        state: DEFAULT_KATANA_VAULT,
        action: "deposit" as never,
      }).ok,
      false,
    );
  });
});

describe("suggestKatanaAction", () => {
  it("prefers remaining inventory over a close", () => {
    assert.equal(
      suggestKatanaAction({
        expired: true,
        userAccount: true,
        userDeposit: BigInt(0),
        userUnredeemed: BigInt(2),
        userWithdrawShares: BigInt(0),
        userDerivative: BigInt(0),
      }),
      "exit",
    );
    assert.equal(
      suggestKatanaAction({
        expired: true,
        userAccount: true,
        userDeposit: BigInt(0),
        userUnredeemed: BigInt(0),
        userWithdrawShares: BigInt(0),
        userDerivative: BigInt(9),
      }),
      "withdraw_expired",
    );
    assert.equal(
      suggestKatanaAction({
        expired: false,
        userAccount: true,
        userDeposit: BigInt(5),
        userUnredeemed: BigInt(0),
        userWithdrawShares: BigInt(0),
        userDerivative: BigInt(0),
      }),
      "instant_withdraw",
    );
    assert.equal(
      suggestKatanaAction({
        expired: true,
        userAccount: true,
        userDeposit: BigInt(0),
        userUnredeemed: BigInt(0),
        userWithdrawShares: BigInt(3),
        userDerivative: BigInt(0),
      }),
      "complete_withdraw",
    );
    assert.equal(
      suggestKatanaAction({
        expired: true,
        userAccount: true,
        userDeposit: BigInt(0),
        userUnredeemed: BigInt(0),
        userWithdrawShares: BigInt(0),
        userDerivative: BigInt(0),
      }),
      "close_user_account",
    );
    assert.equal(
      suggestKatanaAction({
        expired: true,
        userAccount: false,
        userDeposit: BigInt(0),
        userUnredeemed: BigInt(0),
        userWithdrawShares: BigInt(0),
        userDerivative: BigInt(0),
      }),
      null,
    );
  });
});

describe("katana reply readers", () => {
  it("names the RPC fields", () => {
    assert.equal(
      pathLookupNote({
        expired: true,
        paused: false,
        round: "63",
        suggested: "withdraw_expired",
        userDeposit: "0",
        userUnredeemed: "0",
        userWithdrawShares: "0",
        userDerivative: "0",
        lamports: "0",
      }),
      "RPC expired=true paused=false round=63 suggested=withdraw_expired deposit=0 unredeemed=0 queued=0 shares=0 lamports=0.",
    );
  });

  it("reads a broadcast and a defaults payload", () => {
    const signature = "5".repeat(88);
    assert.deepEqual(readKatanaSendResult({ ok: true, signature }), { ok: true, signature });
    assert.deepEqual(readKatanaSendResult({ ok: false, kind: "ambiguous", message: "Check the account." }), {
      ok: false,
      text: "Check the account.",
    });
    assert.equal(readKatanaSendResult({ ok: true, signature: "zz" }), null);
    assert.equal(readKatanaPathDefaults(null), null);
    const defaults = readKatanaPathDefaults({
      ok: true,
      owner: SOL_FUNDED_WALLET_ADDRESS,
      state: DEFAULT_KATANA_VAULT,
      program: "1349iiGjWC7ZTbu6otFmJwztms122jEEnShKgpVnNewy",
      label: "SOL",
      strategy: "Covered call",
      expired: true,
      paused: false,
      round: "63",
      total_shares: "1",
      pending_deposits: "0",
      queued_withdraw_shares: "0",
      locked_amount: "0",
      vault_balance: "0",
      user_account: false,
      user_deposit: "0",
      user_unredeemed: "0",
      user_withdraw_shares: "0",
      user_derivative: "0",
      suggested: null,
      deposit_enabled: false,
      migrate_enabled: false,
      lamports: "0",
    });
    assert.equal(defaults?.ok, true);
    if (!defaults || !defaults.ok) return;
    assert.equal(defaults.suggested, null);
    assert.equal(defaults.deposit_enabled, false);
    assert.equal(readKatanaPathDefaults({ ok: false, message: "Enter a Solana address." })?.ok, false);
  });
});
