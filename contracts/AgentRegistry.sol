// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @title AgentRegistry — On-chain registry for the Agent Labor Market
/// @notice Workers and managers register here. Anyone can read the registry.
///         Supports role-based registration and optional ERC-8004 identity linking.

interface IERC8004Registry {
    function ownerOf(uint256 agentId) external view returns (address);
}

contract AgentRegistry {
    enum Role { Worker, Manager, Client }

    struct Agent {
        string agentId;
        string endpoint;
        string strategy;
        Role   role;
        address owner;
        uint256 registeredAt;
        bool active;
        uint256 erc8004Id;  // 0 = not linked, >0 = verified ERC-8004 identity
    }

    Agent[] public agents;
    mapping(string => uint256) public agentIndex; // agentId → index+1 (0 = not found)

    // Official ERC-8004 Identity Registry on Base
    address public erc8004Registry;

    event AgentRegistered(string indexed agentId, string endpoint, Role role, address owner, uint256 erc8004Id);
    event AgentUpdated(string indexed agentId, string endpoint, string strategy);
    event AgentDeactivated(string indexed agentId);
    event ERC8004Linked(string indexed agentId, uint256 erc8004Id);

    constructor(address _erc8004Registry) {
        erc8004Registry = _erc8004Registry;
    }

    /// @notice Register a new agent. ERC-8004 ID is optional (pass 0 to skip).
    function register(
        string calldata agentId,
        string calldata endpoint,
        string calldata strategy,
        Role role,
        uint256 erc8004Id
    ) external {
        require(bytes(agentId).length > 0, "Empty agent ID");
        require(bytes(endpoint).length > 0, "Empty endpoint");
        require(agentIndex[agentId] == 0, "Already registered");

        // If ERC-8004 ID provided, verify ownership
        if (erc8004Id > 0 && erc8004Registry != address(0)) {
            address idOwner = IERC8004Registry(erc8004Registry).ownerOf(erc8004Id);
            require(idOwner == msg.sender, "You don't own this ERC-8004 ID");
        }

        agents.push(Agent({
            agentId: agentId,
            endpoint: endpoint,
            strategy: strategy,
            role: role,
            owner: msg.sender,
            registeredAt: block.timestamp,
            active: true,
            erc8004Id: erc8004Id
        }));

        agentIndex[agentId] = agents.length;
        emit AgentRegistered(agentId, endpoint, role, msg.sender, erc8004Id);
    }

    /// @notice Link or update ERC-8004 ID after registration.
    function linkERC8004(string calldata agentId, uint256 erc8004Id) external {
        uint256 idx = agentIndex[agentId];
        require(idx > 0, "Not registered");
        Agent storage a = agents[idx - 1];
        require(msg.sender == a.owner, "Not owner");

        if (erc8004Id > 0 && erc8004Registry != address(0)) {
            address idOwner = IERC8004Registry(erc8004Registry).ownerOf(erc8004Id);
            require(idOwner == msg.sender, "You don't own this ERC-8004 ID");
        }

        a.erc8004Id = erc8004Id;
        emit ERC8004Linked(agentId, erc8004Id);
    }

    /// @notice Update endpoint or strategy. Only the agent's owner can update.
    function update(string calldata agentId, string calldata endpoint, string calldata strategy) external {
        uint256 idx = agentIndex[agentId];
        require(idx > 0, "Not registered");
        Agent storage a = agents[idx - 1];
        require(msg.sender == a.owner, "Not owner");

        a.endpoint = endpoint;
        a.strategy = strategy;
        emit AgentUpdated(agentId, endpoint, strategy);
    }

    /// @notice Deactivate an agent. Only the owner can deactivate.
    function deactivate(string calldata agentId) external {
        uint256 idx = agentIndex[agentId];
        require(idx > 0, "Not registered");
        Agent storage a = agents[idx - 1];
        require(msg.sender == a.owner, "Not owner");

        a.active = false;
        emit AgentDeactivated(agentId);
    }

    /// @notice Get total number of registered agents.
    function getAgentCount() external view returns (uint256) {
        return agents.length;
    }

    /// @notice Get active agent count by role.
    function getActiveCountByRole(Role role) external view returns (uint256 count) {
        for (uint256 i = 0; i < agents.length; i++) {
            if (agents[i].active && agents[i].role == role) count++;
        }
    }

    /// @notice Get agent details by index.
    function getAgent(uint256 index) external view returns (
        string memory agentId,
        string memory endpoint,
        string memory strategy,
        Role role,
        address owner,
        uint256 registeredAt,
        bool active,
        uint256 erc8004Id
    ) {
        Agent storage a = agents[index];
        return (a.agentId, a.endpoint, a.strategy, a.role, a.owner, a.registeredAt, a.active, a.erc8004Id);
    }

    /// @notice Check if an agent has a verified ERC-8004 identity.
    function isVerified(string calldata agentId) external view returns (bool) {
        uint256 idx = agentIndex[agentId];
        if (idx == 0) return false;
        return agents[idx - 1].erc8004Id > 0;
    }

    // Backward-compatible aliases for old MinerRegistry interface
    function getMinerCount() external view returns (uint256) { return agents.length; }
    function getMiner(uint256 index) external view returns (
        string memory, string memory, string memory, address, uint256, bool
    ) {
        Agent storage a = agents[index];
        return (a.agentId, a.endpoint, a.strategy, a.owner, a.registeredAt, a.active);
    }
    function getActiveMinerCount() external view returns (uint256 count) {
        for (uint256 i = 0; i < agents.length; i++) {
            if (agents[i].active) count++;
        }
    }
}
