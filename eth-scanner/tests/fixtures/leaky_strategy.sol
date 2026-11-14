// SPDX-License-Identifier: MIT
// Test-only vault + strategy. Not a deployed contract and not an attack.
// `skim` asks the vault to pay the caller, so a conservation check must
// record caller_profit_delta > 0 for an unprivileged caller.
pragma solidity ^0.8.20;

contract StrategyVault {
    address public strategy;

    function setStrategy(address next) external {
        require(strategy == address(0), "set");
        strategy = next;
    }

    function pullTo(address to) external {
        require(msg.sender == strategy, "strategy");
        payable(to).transfer(address(this).balance);
    }

    receive() external payable {}
}

contract Strategy {
    StrategyVault public vault;

    constructor(StrategyVault bound) {
        vault = bound;
    }

    function skim() external {
        vault.pullTo(msg.sender);
    }
}

contract SafeStrategyVault {
    mapping(address => uint256) public claim;

    function deposit() external payable {
        claim[msg.sender] += msg.value;
    }

    function withdraw(uint256 amount) external {
        require(claim[msg.sender] >= amount, "exceeds deposit");
        claim[msg.sender] -= amount;
        payable(msg.sender).transfer(amount);
    }
}
