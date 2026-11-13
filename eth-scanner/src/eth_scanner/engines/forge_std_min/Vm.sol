// SPDX-License-Identifier: MIT
pragma solidity >=0.6.2 <0.9.0;

/// Minimal Vm surface for Halmos/Foundry defensive harnesses.
/// Only cheatcodes Halmos is known to accept (etch/deal/store/load).
interface Vm {
    function etch(address target, bytes calldata newRuntimeBytecode) external;
    function deal(address account, uint256 newBalance) external;
    function store(address target, bytes32 slot, bytes32 value) external;
    function load(address target, bytes32 slot) external view returns (bytes32);
    function envString(string calldata name) external view returns (string memory);
}
