// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @title ProtocolCredits V2 — ERC-20 token for the Agent Labor Market
/// @notice AVNC tokens. Owner controls supply. Faucet has per-address cooldown.

contract ProtocolCreditsV2 {
    string public constant name = "Agent Verification Credits";
    string public constant symbol = "AVNC";
    uint8 public constant decimals = 18;

    uint256 public totalSupply;
    address public owner;

    // Faucet
    uint256 public faucetAmount = 20 * 1e18;
    uint256 public faucetCooldown = 1 days;
    mapping(address => uint256) public lastFaucetClaim;

    // Standard ERC-20
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event FaucetClaim(address indexed agent, uint256 amount);

    constructor(uint256 initialSupply) {
        owner = msg.sender;
        _mint(msg.sender, initialSupply * 1e18);
    }

    function faucet() external {
        require(
            block.timestamp >= lastFaucetClaim[msg.sender] + faucetCooldown,
            "Faucet: wait for cooldown"
        );
        lastFaucetClaim[msg.sender] = block.timestamp;
        _mint(msg.sender, faucetAmount);
        emit FaucetClaim(msg.sender, faucetAmount);
    }

    function setFaucetAmount(uint256 amount) external {
        require(msg.sender == owner, "Not owner");
        faucetAmount = amount;
    }

    function setFaucetCooldown(uint256 cooldown) external {
        require(msg.sender == owner, "Not owner");
        faucetCooldown = cooldown;
    }

    function transfer(address to, uint256 value) external returns (bool) {
        require(balanceOf[msg.sender] >= value, "Insufficient balance");
        balanceOf[msg.sender] -= value;
        balanceOf[to] += value;
        emit Transfer(msg.sender, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        require(balanceOf[from] >= value, "Insufficient balance");
        require(allowance[from][msg.sender] >= value, "Insufficient allowance");
        balanceOf[from] -= value;
        allowance[from][msg.sender] -= value;
        balanceOf[to] += value;
        emit Transfer(from, to, value);
        return true;
    }

    function _mint(address to, uint256 value) internal {
        totalSupply += value;
        balanceOf[to] += value;
        emit Transfer(address(0), to, value);
    }
}
