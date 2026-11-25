// SPDX-License-Identifier: MIT
// Original ERC-20 rules for the Certora CLI. The prover itself is not linked.

methods {
    function balanceOf(address) external returns (uint256) envfree;
    function totalSupply() external returns (uint256) envfree;
    function allowance(address, address) external returns (uint256) envfree;
    function transfer(address, uint256) external returns (bool);
    function transferFrom(address, address, uint256) external returns (bool);
    function approve(address, uint256) external returns (bool);
}

/// A caller who is not the holder, and who has no allowance, cannot reduce that balance.
rule strangerCannotReduceBalance(method f, address holder) {
    env e;
    require e.msg.sender != holder;
    require allowance(holder, e.msg.sender) == 0;
    uint256 before = balanceOf(holder);
    calldataarg args;
    f(e, args);
    assert balanceOf(holder) >= before;
}

/// transfer and approve do not change the recorded supply.
rule transferConservesSupply(address to, uint256 amount) {
    env e;
    uint256 before = totalSupply();
    transfer(e, to, amount);
    assert totalSupply() == before;
}

rule approveConservesSupply(address spender, uint256 amount) {
    env e;
    uint256 before = totalSupply();
    approve(e, spender, amount);
    assert totalSupply() == before;
}

/// approve records exactly the amount the caller asked for.
rule approveSetsAllowance(address spender, uint256 amount) {
    env e;
    approve(e, spender, amount);
    assert allowance(e.msg.sender, spender) == amount;
}
