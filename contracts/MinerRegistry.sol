// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @title MinerRegistry — On-chain registry for verification network miners
/// @notice Miners register once on-chain. The registry persists across server restarts.
///         Anyone can read the registry to discover miners. No middleman required.
contract MinerRegistry {
    struct Miner {
        string agentId;
        string endpoint;    // Public URL (e.g., https://my-miner.railway.app)
        string strategy;    // Analysis strategy (e.g., "security-focused")
        address owner;      // Wallet that registered this miner
        uint256 registeredAt;
        bool active;
    }

    Miner[] public miners;
    mapping(string => uint256) public agentIndex; // agentId → index+1 (0 means not found)

    event MinerRegistered(string indexed agentId, string endpoint, string strategy, address owner);
    event MinerUpdated(string indexed agentId, string endpoint, string strategy);
    event MinerDeactivated(string indexed agentId);

    /// @notice Register a new miner. Anyone can register.
    function register(string calldata agentId, string calldata endpoint, string calldata strategy) external {
        require(bytes(agentId).length > 0, "Empty agent ID");
        require(bytes(endpoint).length > 0, "Empty endpoint");
        require(agentIndex[agentId] == 0, "Already registered");

        miners.push(Miner({
            agentId: agentId,
            endpoint: endpoint,
            strategy: strategy,
            owner: msg.sender,
            registeredAt: block.timestamp,
            active: true
        }));

        agentIndex[agentId] = miners.length; // 1-indexed

        emit MinerRegistered(agentId, endpoint, strategy, msg.sender);
    }

    /// @notice Update endpoint or strategy. Only the miner's owner can update.
    function update(string calldata agentId, string calldata endpoint, string calldata strategy) external {
        uint256 idx = agentIndex[agentId];
        require(idx > 0, "Not registered");
        Miner storage m = miners[idx - 1];
        require(msg.sender == m.owner, "Not owner");

        m.endpoint = endpoint;
        m.strategy = strategy;

        emit MinerUpdated(agentId, endpoint, strategy);
    }

    /// @notice Deactivate a miner. Only the owner can deactivate.
    function deactivate(string calldata agentId) external {
        uint256 idx = agentIndex[agentId];
        require(idx > 0, "Not registered");
        Miner storage m = miners[idx - 1];
        require(msg.sender == m.owner, "Not owner");

        m.active = false;

        emit MinerDeactivated(agentId);
    }

    /// @notice Get total number of registered miners (including inactive).
    function getMinerCount() external view returns (uint256) {
        return miners.length;
    }

    /// @notice Get active miners count.
    function getActiveMinerCount() external view returns (uint256 count) {
        for (uint256 i = 0; i < miners.length; i++) {
            if (miners[i].active) count++;
        }
    }

    /// @notice Get miner details by index.
    function getMiner(uint256 index) external view returns (
        string memory agentId,
        string memory endpoint,
        string memory strategy,
        address owner,
        uint256 registeredAt,
        bool active
    ) {
        Miner storage m = miners[index];
        return (m.agentId, m.endpoint, m.strategy, m.owner, m.registeredAt, m.active);
    }
}
