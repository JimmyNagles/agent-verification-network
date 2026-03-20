// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @title AgentScorer — On-chain score recording for the Agent Verification Network
/// @notice Records miner agent verification scores, queryable by anyone.
///         Deployed on Base Sepolia as part of The Synthesis hackathon (ERC-8004 track).
contract AgentScorer {
    struct Score {
        string agentId;
        string taskId;
        uint256 score;      // Score * 10000 (e.g., 0.7800 = 7800)
        uint256 timestamp;
        uint256 round;
    }

    address public owner;
    Score[] public scores;
    mapping(string => uint256) public agentScoreCount;
    mapping(string => uint256) public agentBestScore;

    event ScoreRecorded(
        string indexed agentId,
        string taskId,
        uint256 score,
        uint256 round,
        uint256 timestamp
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    /// @notice Record a miner's verification score after a validation round
    function recordScore(
        string calldata agentId,
        string calldata taskId,
        uint256 score,
        uint256 round
    ) external onlyOwner {
        scores.push(Score({
            agentId: agentId,
            taskId: taskId,
            score: score,
            timestamp: block.timestamp,
            round: round
        }));

        agentScoreCount[agentId]++;
        if (score > agentBestScore[agentId]) {
            agentBestScore[agentId] = score;
        }

        emit ScoreRecorded(agentId, taskId, score, round, block.timestamp);
    }

    /// @notice Get total number of recorded scores
    function getScoreCount() external view returns (uint256) {
        return scores.length;
    }

    /// @notice Get a specific score by index
    function getScoreAt(uint256 index) external view returns (
        string memory agentId,
        string memory taskId,
        uint256 score,
        uint256 timestamp,
        uint256 round
    ) {
        Score storage s = scores[index];
        return (s.agentId, s.taskId, s.score, s.timestamp, s.round);
    }
}
