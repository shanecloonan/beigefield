import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { automationSource } from "./uton-automation";

describe("uTON automation listing", () => {
  it("queues later names after a bounce and stays a listing", () => {
    const joined = `${automationSource.afterBurn1.code}\n${automationSource.queueAfterBounce.code}`;
    assert.equal(automationSource.afterBurn1.file, "automation/after-burn-1.ts");
    assert.equal(automationSource.queueAfterBounce.file, "automation/queue-after-bounce.ts");
    assert.match(automationSource.afterBurn1.code, /function watchBounce/);
    assert.match(automationSource.afterBurn1.code, /"burn-2"/);
    assert.match(automationSource.afterBurn1.code, /"redeem-notification"/);
    assert.match(automationSource.afterBurn1.code, /"withdraw"/);
    assert.match(automationSource.queueAfterBounce.code, /function nextAfter/);
    assert.match(automationSource.queueAfterBounce.code, /"burn-2"/);
    assert.doesNotMatch(
      joined,
      /sendTransaction|\/api\/ton\/send|toncenter|tonapi|fetch\(|beginCell|sign\(/,
    );
  });
});
