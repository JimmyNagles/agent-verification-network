// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @title AgentScorerV2 — On-chain rating records for the Agent Labor Market
/// @notice Records worker quality ratings. Queryable by anyone.
///         Supports ownership transfer for operational safety.
contract AgentScorerV2 {
    struct Rating {
        string agentId;
        string jobId;
        uint256 score;      // Score * 10000 (e.g., 0.7800 = 7800)
        uint256 timestamp;
        uint256 round;
    }

    address public owner;
    address public pendingOwner;
    Rating[] public ratings;
    mapping(string => uint256) public agentRatingCount;
    mapping(string => uint256) public agentBestRating;

    event RatingRecorded(
        string indexed agentId,
        string jobId,
        uint256 score,
        uint256 round,
        uint256 timestamp
    );
    event OwnershipTransferStarted(address indexed currentOwner, address indexed newOwner);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    /// @notice Record a worker's quality rating after a job round
    function recordRating(
        string calldata agentId,
        string calldata jobId,
        uint256 score,
        uint256 round
    ) external onlyOwner {
        ratings.push(Rating({
            agentId: agentId,
            jobId: jobId,
            score: score,
            timestamp: block.timestamp,
            round: round
        }));

        agentRatingCount[agentId]++;
        if (score > agentBestRating[agentId]) {
            agentBestRating[agentId] = score;
        }

        emit RatingRecorded(agentId, jobId, score, round, block.timestamp);
    }

    // Backward-compatible alias
    function recordScore(
        string calldata agentId,
        string calldata taskId,
        uint256 score,
        uint256 round
    ) external onlyOwner {
        ratings.push(Rating({
            agentId: agentId,
            jobId: taskId,
            score: score,
            timestamp: block.timestamp,
            round: round
        }));
        agentRatingCount[agentId]++;
        if (score > agentBestRating[agentId]) {
            agentBestRating[agentId] = score;
        }
        emit RatingRecorded(agentId, taskId, score, round, block.timestamp);
    }

    function getRatingCount() external view returns (uint256) {
        return ratings.length;
    }

    function getRatingAt(uint256 index) external view returns (
        string memory agentId, string memory jobId,
        uint256 score, uint256 timestamp, uint256 round
    ) {
        Rating storage r = ratings[index];
        return (r.agentId, r.jobId, r.score, r.timestamp, r.round);
    }

    // Backward-compatible aliases
    function getScoreCount() external view returns (uint256) { return ratings.length; }
    function getScoreAt(uint256 index) external view returns (
        string memory, string memory, uint256, uint256, uint256
    ) {
        Rating storage r = ratings[index];
        return (r.agentId, r.jobId, r.score, r.timestamp, r.round);
    }

    /// @notice Start ownership transfer (two-step for safety)
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Invalid address");
        pendingOwner = newOwner;
        emit OwnershipTransferStarted(owner, newOwner);
    }

    /// @notice New owner accepts the transfer
    function acceptOwnership() external {
        require(msg.sender == pendingOwner, "Not pending owner");
        emit OwnershipTransferred(owner, pendingOwner);
        owner = pendingOwner;
        pendingOwner = address(0);
    }
}
