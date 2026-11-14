// SPDX-License-Identifier: MIT
// Test-only vault. Not a deployed contract and not an attack.
// `poke` moves the contract balance to the caller so the conservation
// checker has a local case that must rank as a profit-invariant break.
pragma solidity ^0.8.20;

contract LeakyVault {
    function poke() external {
        payable(msg.sender).transfer(address(this).balance);
    }
}

contract SafeVault {
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
