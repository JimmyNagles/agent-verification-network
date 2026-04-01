// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @title AgenticCommerceV3 — Job marketplace for the Agent Labor Market
/// @notice Full job lifecycle: create → fund → submit → complete/reject
///         Manager earns a fee on every completed job. Worker gets the rest.
///         Includes reentrancy protection.

interface IERC20 {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
}

contract AgenticCommerceV3 {
    enum State { Open, Funded, Submitted, Completed, Rejected, Expired }

    struct Job {
        address client;
        address worker;
        address manager;
        bytes32 description;
        uint256 budget;
        address token;          // address(0) = ETH
        State   state;
        bytes32 deliverable;
        uint256 createdAt;
    }

    Job[] public jobs;
    address public owner;

    // Fee: basis points (1500 = 15%)
    uint256 public managerFeeBps = 1500;
    address public feeRecipient;

    // Stats
    uint256 public totalPaidOut;
    uint256 public totalFees;

    // Reentrancy guard
    uint256 private _locked = 1;
    modifier nonReentrant() {
        require(_locked == 1, "Reentrant call");
        _locked = 2;
        _;
        _locked = 1;
    }

    event JobCreated(uint256 indexed jobId, address indexed client, address manager, uint256 budget);
    event JobFunded(uint256 indexed jobId, address indexed client, uint256 amount);
    event JobSubmitted(uint256 indexed jobId, address indexed worker, bytes32 deliverable);
    event JobCompleted(uint256 indexed jobId, address indexed worker, uint256 payout, uint256 fee);
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
            managerFeeBps = _feeBps;
        }
    }

    /// @notice Create a new job. Worker is unset until someone submits.
    function createJob(
        address manager,
        bytes32 description,
        address token,
        uint256 budget
    ) external returns (uint256 jobId) {
        require(manager != address(0), "Invalid manager");
        require(budget > 0, "Budget must be > 0");

        jobId = jobs.length;
        jobs.push(Job({
            client: msg.sender,
            worker: address(0),
            manager: manager,
            description: description,
            budget: budget,
            token: token,
            state: State.Open,
            deliverable: bytes32(0),
            createdAt: block.timestamp
        }));

        emit JobCreated(jobId, msg.sender, manager, budget);
    }

    /// @notice Client escrows funds for the job.
    function fund(uint256 jobId) external payable nonReentrant {
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

    /// @notice Worker submits a deliverable hash.
    function submit(uint256 jobId, bytes32 deliverable) external {
        Job storage job = jobs[jobId];
        require(job.state == State.Funded, "Not funded");
        require(deliverable != bytes32(0), "Empty deliverable");

        job.worker = msg.sender;
        job.deliverable = deliverable;
        job.state = State.Submitted;

        emit JobSubmitted(jobId, msg.sender, deliverable);
    }

    /// @notice Manager approves work — funds split between worker and fee recipient.
    function complete(uint256 jobId) external nonReentrant {
        Job storage job = jobs[jobId];
        require(msg.sender == job.manager, "Only manager");
        require(job.state == State.Submitted, "Not submitted");

        job.state = State.Completed;

        uint256 fee = (job.budget * managerFeeBps) / 10000;
        uint256 payout = job.budget - fee;

        // State is already updated before transfers (checks-effects-interactions)
        if (fee > 0) {
            _transfer(job.token, feeRecipient, fee);
            totalFees += fee;
        }
        _transfer(job.token, job.worker, payout);
        totalPaidOut += payout;

        emit JobCompleted(jobId, job.worker, payout, fee);
    }

    /// @notice Manager rejects work — funds return to client.
    function reject(uint256 jobId) external nonReentrant {
        Job storage job = jobs[jobId];
        require(msg.sender == job.manager, "Only manager");
        require(job.state == State.Submitted, "Not submitted");

        job.state = State.Rejected;
        _transfer(job.token, job.client, job.budget);

        emit JobRejected(jobId, job.client, job.budget);
    }

    /// @notice Get full job details.
    function getJob(uint256 jobId) external view returns (
        address client, address worker, address manager,
        bytes32 description, uint256 budget, address token,
        State state, bytes32 deliverable, uint256 createdAt
    ) {
        Job storage j = jobs[jobId];
        return (j.client, j.worker, j.manager, j.description,
                j.budget, j.token, j.state, j.deliverable, j.createdAt);
    }

    function getJobCount() external view returns (uint256) {
        return jobs.length;
    }

    function setFee(uint256 newFeeBps) external onlyOwner {
        require(newFeeBps <= 5000, "Fee too high");
        managerFeeBps = newFeeBps;
        emit FeeUpdated(newFeeBps);
    }

    function setFeeRecipient(address newRecipient) external onlyOwner {
        require(newRecipient != address(0), "Invalid recipient");
        feeRecipient = newRecipient;
    }

    // Backward compatibility: old field names
    function validatorFeeBps() external view returns (uint256) { return managerFeeBps; }

    function _transfer(address token, address to, uint256 amount) internal {
        if (token == address(0)) {
            (bool ok, ) = to.call{value: amount}("");
            require(ok, "ETH transfer failed");
        } else {
            require(IERC20(token).transfer(to, amount), "Token transfer failed");
        }
    }
}
