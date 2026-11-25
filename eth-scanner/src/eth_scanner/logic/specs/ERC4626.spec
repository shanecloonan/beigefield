// SPDX-License-Identifier: MIT
// Original ERC-4626 rules for the Certora CLI. The prover itself is not linked.

methods {
    function balanceOf(address) external returns (uint256) envfree;
    function totalSupply() external returns (uint256) envfree;
    function totalAssets() external returns (uint256) envfree;
    function convertToAssets(uint256) external returns (uint256) envfree;
    function convertToShares(uint256) external returns (uint256) envfree;
    function previewDeposit(uint256) external returns (uint256) envfree;
    function allowance(address, address) external returns (uint256) envfree;
    function deposit(uint256, address) external returns (uint256);
    function mint(uint256, address) external returns (uint256);
    function withdraw(uint256, address, address) external returns (uint256);
    function redeem(uint256, address, address) external returns (uint256);
}

/// Claims cannot exceed the assets the vault reports.
rule assetsCoverClaims() {
    uint256 supply = totalSupply();
    assert totalAssets() >= convertToAssets(supply);
}

/// Deposit preview does not promise more assets back than were deposited.
rule roundingFavorsVault(uint256 assets) {
    uint256 shares = previewDeposit(assets);
    uint256 back = convertToAssets(shares);
    assert back <= assets;
}

/// A zero deposit does not mint shares. That is the donation/inflation check.
rule zeroDepositMintsNothing(env e, address receiver) {
    uint256 before = balanceOf(receiver);
    deposit(e, 0, receiver);
    assert balanceOf(receiver) == before;
}

/// A deposit does not mint more shares than convertToShares reports.
rule depositDoesNotInflate(env e, uint256 assets, address receiver) {
    require e.msg.sender == receiver;
    uint256 before = balanceOf(receiver);
    uint256 quoted = convertToShares(assets);
    deposit(e, assets, receiver);
    assert balanceOf(receiver) <= before + quoted;
}

/// A stranger with no allowance cannot reduce someone else's shares.
rule strangerCannotReduceShares(method f, address holder) {
    env e;
    require e.msg.sender != holder;
    require allowance(holder, e.msg.sender) == 0;
    uint256 before = balanceOf(holder);
    calldataarg args;
    f(e, args);
    assert balanceOf(holder) >= before;
}
