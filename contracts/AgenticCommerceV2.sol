// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @title AgenticCommerceV2 — Job marketplace with validator fee split
/// @notice Full ERC-8183 job lifecycle: create → fund → submit → complete/reject
///         Validator earns a fee on every completed job. Miner gets the rest.

interface IERC20 {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
}

contract AgenticCommerceV2 {
    enum State { Open, Funded, Submitted, Completed, Rejected, Expired }

    struct Job {
        address client;
        address provider;
        address evaluator;
        bytes32 description;
        uint256 budget;
        address token;          // address(0) = ETH
        State   state;
        bytes32 deliverable;
        uint256 createdAt;
    }

    Job[] public jobs;
    address public owner;

    // Fee: basis points (1000 = 10%, 1500 = 15%)
    uint256 public validatorFeeBps = 1500; // 15% default
    address public feeRecipient;

    // Stats
    uint256 public totalPaidOut;
    uint256 public totalFees;

    event JobCreated(uint256 indexed jobId, address indexed client, address evaluator, uint256 budget);
    event JobFunded(uint256 indexed jobId, address indexed client, uint256 amount);
    event JobSubmitted(uint256 indexed jobId, address indexed provider, bytes32 deliverable);
    event JobCompleted(uint256 indexed jobId, address indexed provider, uint256 payout, uint256 fee);
    event JobRejected(uint256 indexed jobId, address indexed client, uint256 refund);
    event FeeUpdated(uint256 newFeeBps);

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    constructor(address _feeRecipient, uint256 _feeBps) {
        owner = msg.sender;
        feeRecipient = _feeRecipient;
        if (_feeBps > 0 && _feeBps <= 5000) {
            validatorFeeBps = _feeBps;
        }
    }

    /// @notice Create a new job. Provider is unset until someone submits.
    function createJob(
        address evaluator,
        bytes32 description,
        address token,
        uint256 budget
    ) external returns (uint256 jobId) {
        require(evaluator != address(0), "Invalid evaluator");
        require(budget > 0, "Budget must be > 0");

        jobId = jobs.length;
        jobs.push(Job({
            client: msg.sender,
            provider: address(0),
            evaluator: evaluator,
            description: description,
            budget: budget,
            token: token,
            state: State.Open,
            deliverable: bytes32(0),
            createdAt: block.timestamp
        }));

        emit JobCreated(jobId, msg.sender, evaluator, budget);
    }

    /// @notice Client escrows funds for the job.
    function fund(uint256 jobId) external payable {
        Job storage job = jobs[jobId];
        require(msg.sender == job.client, "Only client");
        require(job.state == State.Open, "Not open");

        if (job.token == address(0)) {
            require(msg.value == job.budget, "Wrong ETH amount");
        } else {
            require(msg.value == 0, "No ETH for token jobs");
            require(
                IERC20(job.token).transferFrom(msg.sender, address(this), job.budget),
                "Transfer failed"
            );
        }

        job.state = State.Funded;
        emit JobFunded(jobId, msg.sender, job.budget);
    }

    /// @notice Provider submits a deliverable hash.
    function submit(uint256 jobId, bytes32 deliverable) external {
        Job storage job = jobs[jobId];
        require(job.state == State.Funded, "Not funded");
        require(deliverable != bytes32(0), "Empty deliverable");

        job.provider = msg.sender;
        job.deliverable = deliverable;
        job.state = State.Submitted;

        emit JobSubmitted(jobId, msg.sender, deliverable);
    }

    /// @notice Evaluator approves work — funds split between provider and fee recipient.
    function complete(uint256 jobId) external {
        Job storage job = jobs[jobId];
        require(msg.sender == job.evaluator, "Only evaluator");
        require(job.state == State.Submitted, "Not submitted");

        job.state = State.Completed;

        uint256 fee = (job.budget * validatorFeeBps) / 10000;
        uint256 payout = job.budget - fee;

        if (fee > 0) {
            _transfer(job.token, feeRecipient, fee);
            totalFees += fee;
        }
        _transfer(job.token, job.provider, payout);
        totalPaidOut += payout;

        emit JobCompleted(jobId, job.provider, payout, fee);
    }

    /// @notice Evaluator rejects work — funds return to client.
    function reject(uint256 jobId) external {
        Job storage job = jobs[jobId];
        require(msg.sender == job.evaluator, "Only evaluator");
        require(job.state == State.Submitted, "Not submitted");

        job.state = State.Rejected;
        _transfer(job.token, job.client, job.budget);

        emit JobRejected(jobId, job.client, job.budget);
    }

    /// @notice Get full job details.
    function getJob(uint256 jobId) external view returns (
        address client, address provider, address evaluator,
        bytes32 description, uint256 budget, address token,
        State state, bytes32 deliverable, uint256 createdAt
    ) {
        Job storage j = jobs[jobId];
        return (j.client, j.provider, j.evaluator, j.description,
                j.budget, j.token, j.state, j.deliverable, j.createdAt);
    }

    /// @notice Total number of jobs created.
    function getJobCount() external view returns (uint256) {
        return jobs.length;
    }

    /// @notice Update validator fee (owner only, max 50%).
    function setFee(uint256 newFeeBps) external onlyOwner {
        require(newFeeBps <= 5000, "Fee too high");
        validatorFeeBps = newFeeBps;
        emit FeeUpdated(newFeeBps);
    }

    /// @notice Update fee recipient (owner only).
    function setFeeRecipient(address newRecipient) external onlyOwner {
        require(newRecipient != address(0), "Invalid recipient");
        feeRecipient = newRecipient;
    }

    function _transfer(address token, address to, uint256 amount) internal {
        if (token == address(0)) {
            (bool ok, ) = to.call{value: amount}("");
            require(ok, "ETH transfer failed");
        } else {
            require(IERC20(token).transfer(to, amount), "Token transfer failed");
        }
    }
}
