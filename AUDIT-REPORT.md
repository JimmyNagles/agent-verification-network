# AGENT LABOR MARKET — Full Audit (4-Agent Consensus)
Date: 2026-03-31
Branch: feature/enforce-role-separation

================================================================
## BACKEND
================================================================
## OUTBOX

# COMPLETE SECURITY & CODE AUDIT — Agent Labor Market

**Auditor:** Claude Opus 4.6 (Backend Agent)
**Date:** 2026-03-31
**Branch:** `feature/enforce-role-separation`
**Scope:** All files in `agent_market/`, `contracts/`, `tests/`, `web/app/`, config files
**Verdict:** **NOT PRODUCTION-READY** — 7 critical, 12 high, 18 medium findings

---

## CRITICAL FINDINGS (7)

### C1. Hardcoded Supabase Anon Key in Source Code
- **File:** `agent_market/keys.py:28`
- **Issue:** The Supabase anon key is hardcoded as a default value: `eyJhbGciOiJIUzI1NiIs...`. This key is committed to the public GitHub repo. Anyone can read/write to your Supabase tables using this key.
- **Impact:** Full read/write access to `api_keys`, `completed_jobs`, `registered_workers`, `marketplace_jobs`, `usage_log` tables. Attacker can steal API keys, forge job completions, drain earnings.
- **Fix:** Remove the hardcoded default. Require `SUPABASE_KEY` as an env var only. Add Row Level Security (RLS) policies in Supabase.

### C2. Hardcoded Alchemy RPC API Key in Source Code
- **File:** `agent_market/erc8004.py:21`, `agent_market/x402.py:160`
- **Issue:** Alchemy API key `VkqT8RyCceRMz0G4PbTQYJjkG5KMFIQZ` is hardcoded in two files as a fallback RPC URL. This is in a public repo.
- **Impact:** Anyone can use your Alchemy API key, exhaust your RPC quota, or monitor your on-chain queries.
- **Fix:** Remove hardcoded API keys. Use env var `BASE_RPC_URL` with no default, or use a public RPC like `https://mainnet.base.org`.

### C3. Race Condition in Credit Deduction (Double-Spend)
- **File:** `agent_market/keys.py:155-188`
- **Issue:** `use_credit()` does a read-then-write: reads `credits_remaining`, then patches `credits_remaining - 1`. Between the read and the write, another request can read the same value, causing double-spend. No database-level atomicity.
- **Impact:** A client can send concurrent requests and get more verifications than their credit balance allows. At scale, this drains the free tier.
- **Fix:** Use Supabase RPC with a SQL function: `UPDATE api_keys SET credits_remaining = credits_remaining - 1 WHERE key_hash = $1 AND credits_remaining > 0 RETURNING credits_remaining`. This is atomic.

### C4. Race Condition in Marketplace Job Claim
- **File:** `agent_market/api/server.py:907-996`
- **Issue:** `claim_marketplace_job()` reads the job, checks if it's claimed, then writes the claim. Two workers sending simultaneous claims can both succeed because there's no database-level lock or unique constraint enforcement.
- **Impact:** Two workers can claim the same job, both do the work, but only one gets paid. Or worse, both submit and the second one fails silently.
- **Fix:** Use a Supabase RPC with `UPDATE ... WHERE claimed_by IS NULL RETURNING *` to make the claim atomic.

### C5. No Authentication on Worker/Manager Registration
- **File:** `agent_market/api/server.py:582-675`
- **Issue:** `POST /register-worker` and `POST /register-manager` require no API key, no authentication, no proof of identity. Anyone can register any endpoint as a worker. The only check is a health ping.
- **Impact:** An attacker can register a malicious endpoint that returns crafted responses to poison consensus scoring, manipulate the leaderboard, or return false "clean" results to clients. Sybil attacks are trivial — register 100 fake workers to dominate consensus.
- **Fix:** Require API key authentication for registration. Consider requiring an on-chain stake or signature proving wallet ownership.

### C6. Reentrancy in AgenticCommerceV2.complete()
- **File:** `contracts/AgenticCommerceV2.sol:119-137`
- **Issue:** `complete()` calls `_transfer()` which uses low-level `.call{value: amount}("")` for ETH transfers. The state update (`job.state = State.Completed`) happens BEFORE the transfers, which is correct for the state. However, `totalFees` and `totalPaidOut` are updated AFTER the external calls. If the `feeRecipient` or `provider` is a contract with a fallback function, they could re-enter and call `complete()` again — but the state check (`require(job.state == State.Submitted)`) would prevent re-entry for the same job. **Mitigated by state check**, but the pattern is still risky if future modifications add more state updates after the call.
- **Revised severity:** MEDIUM (mitigated but fragile pattern). Use checks-effects-interactions or ReentrancyGuard.

### C7. AgentScorer is Owner-Only, Single Point of Failure
- **File:** `contracts/AgentScorer.sol:29-44`
- **Issue:** `recordScore()` is `onlyOwner`. If the owner key is compromised, an attacker can write arbitrary scores for any agent. If the key is lost, no scores can ever be recorded again. There's no way to transfer ownership.
- **Impact:** Complete compromise of the reputation system.
- **Fix:** Add `transferOwnership()`, consider a multi-sig, or allow multiple authorized callers.

---

## HIGH FINDINGS (12)

### H1. No Input Sanitization on Supabase Queries
- **File:** `agent_market/keys.py:141`, `agent_market/api/server.py:929,1016,1549,1602`
- **Issue:** User-supplied values like `agent_name`, `agent_id`, `task_id` are interpolated directly into Supabase REST API query strings: `f"api_keys?agent_name=eq.{agent_name}"`. If `agent_name` contains characters like `&`, `?`, or PostgREST operators, it can manipulate the query.
- **Impact:** PostgREST injection — attacker could read other users' data, bypass filters, or cause errors.
- **Fix:** URL-encode all user-supplied values with `urllib.parse.quote()`.

### H2. Faucet Has No Rate Limiting (API Level)
- **File:** `agent_market/api/server.py:1413-1434`
- **Issue:** The `/faucet` endpoint has no rate limiting. The on-chain `ProtocolCredits.faucet()` has a 1-day cooldown per address, but the API-level faucet at `/faucet` calls `_token.transfer()` from the manager's own wallet — bypassing the on-chain cooldown entirely.
- **Impact:** An attacker can drain the manager's AVNC token balance by calling `/faucet` repeatedly with different addresses.
- **Fix:** Add per-address rate limiting at the API level. Or call the on-chain `faucet()` function instead of `transfer()`.

### H3. Withdraw Endpoint Zeroes Balance Before Confirming Transfer
- **File:** `agent_market/api/server.py:1610-1646`
- **Issue:** The `/withdraw` endpoint sends tokens, then zeros the balance in Supabase. If the Supabase patch fails (network error, timeout), the worker loses their balance record but the tokens were already sent. The reverse order is also risky — if you zero first and the transfer fails, the balance is lost.
- **Impact:** Workers could lose earned AVNC due to partial failures.
- **Fix:** Use a two-phase approach: mark the withdrawal as "pending" in Supabase, send tokens, then mark as "completed". Or use a database transaction.

### H4. CORS Allows All Origins
- **File:** `agent_market/api/server.py:46-51`
- **Issue:** `allow_origins=["*"]` with `allow_methods=["*"]` and `allow_headers=["*"]`. Any website can make authenticated requests to your API.
- **Impact:** A malicious website could use a user's browser to call `/withdraw`, `/faucet`, or other authenticated endpoints if the user has credentials stored.
- **Fix:** Restrict `allow_origins` to your known frontend domains.

### H5. In-Memory State Loss on Restart
- **File:** `agent_market/api/server.py:80-85`
- **Issue:** `results`, `_registered_workers`, `_registered_managers`, `_total_verifications`, `_register_rate_limit` are all in-memory dicts/lists. Workers loaded from Supabase on startup, but `results` (verification results) are never persisted outside individual Supabase log entries.
- **Impact:** Server restart loses all pending verification results. Rate limiting resets. `/status/{task_id}` returns 404 for all previous tasks.
- **Fix:** Persist results to Supabase. Use Redis or similar for rate limiting.

### H6. No Timeout or Circuit Breaker on Worker Calls
- **File:** `agent_market/api/server.py:419`, `agent_market/manager/forward.py:262`
- **Issue:** Worker HTTP calls use `urllib.request.urlopen(req, timeout=30)`. If a worker is slow or unresponsive, the API blocks for 30 seconds per worker. With N workers, total blocking time is N*30s. Workers are called sequentially, not in parallel.
- **Impact:** A single slow or malicious worker can cause the entire `/verify` endpoint to hang for 30+ seconds, degrading service for all clients.
- **Fix:** Call workers in parallel using `asyncio.gather()` with timeouts. Add circuit breakers for repeatedly failing workers.

### H7. ProtocolCredits Has Unlimited Minting via Faucet
- **File:** `contracts/ProtocolCredits.sol:37-45`
- **Issue:** The `faucet()` function calls `_mint()`, creating tokens from nothing. There is no supply cap. Any address can call it every 24 hours to mint 20 AVNC. Over time, this inflates the supply infinitely.
- **Impact:** AVNC token has no scarcity. If used for real payments, the token value trends to zero.
- **Fix:** Add a maximum supply cap. Or change the faucet to transfer from a treasury rather than minting.

### H8. MinerRegistry Has No Deactivation by Admin
- **File:** `contracts/MinerRegistry.sol:57-67`
- **Issue:** Only the registering wallet can deactivate a miner. There's no admin/owner function to deactivate malicious miners.
- **Impact:** If a worker registers and then starts returning malicious results, the protocol operator cannot remove them from the on-chain registry.
- **Fix:** Add an `ownerDeactivate()` function.

### H9. Logger Writes to Local File (Race Condition Under Concurrency)
- **File:** `agent_market/logger.py:17-51`
- **Issue:** `log_event()` does `_load_log()` → append → `_save_log()` with no locking. Under concurrent requests (FastAPI is async), two events can read the same file, append their event, and write — causing one event to be lost.
- **Impact:** Lost audit trail entries under load.
- **Fix:** Use a proper logging framework, or add file locking, or write to a database.

### H10. chain.py Hardcodes "base-sepolia" in Return Value
- **File:** `agent_market/chain.py:98`
- **Issue:** `record_score()` returns `"chain": "base-sepolia"` hardcoded, even though `self.chain_id` might be 8453 (mainnet). The chain detection in `__init__` is correct, but the return value ignores it.
- **Impact:** Misleading metadata — clients think scores are on testnet when they're on mainnet.
- **Fix:** Use `"chain": "base-mainnet" if self.chain_id == 8453 else "base-sepolia"`.

### H11. AgenticCommerceV2 Has No Job Expiry Mechanism
- **File:** `contracts/AgenticCommerceV2.sol`
- **Issue:** Jobs can be created and funded but there's no way to expire or cancel them. If an evaluator disappears, funded ETH/tokens are locked forever. The `State.Expired` enum exists but no function transitions to it.
- **Impact:** Permanent fund lockup for abandoned jobs.
- **Fix:** Add a `cancel()` or `expire()` function with a time-based condition.

### H12. Marketplace Job Submit Has No Claim Verification
- **File:** `agent_market/api/server.py:999-1177`
- **Issue:** `POST /jobs/{task_id}/submit` does not verify that the submitter is the worker who claimed the job. Any authenticated user can submit a result for any job, even one claimed by someone else.
- **Impact:** Worker A claims a job, Worker B submits a garbage result and gets paid.
- **Fix:** Check `submitter_name == job.get("claimed_by")` before accepting the submission.

---

## MEDIUM FINDINGS (18)

### M1. No Validation on `task_type` in Server
- **File:** `agent_market/api/server.py:195`
- **Issue:** `task_type` field in `VerifyRequest` accepts any string. No validation against allowed types (`code-verification`, `text-review`, `image-analysis`).
- **Fix:** Add a Pydantic validator or use `Literal["code-verification", "text-review", "image-analysis"]`.

### M2. Worker Forward Swallows Exceptions
- **File:** `agent_market/worker/forward.py:69-78`
- **Issue:** On any exception during analysis, the worker returns `passed=True, confidence=0.0, issues=[]`. A crash in the analyzer means the worker reports "code is clean."
- **Fix:** Return `passed=False` on error, or raise the exception.

### M3. Spot Check Templates Are Static and Memorizable
- **File:** `agent_market/manager/spot_check.py:84-335`
- **Issue:** Only 12 code templates with basic randomization (function names, variable names). A malicious worker can hash the code structure and look up the expected answer. The `_randomize()` method only changes superficial names.
- **Impact:** Workers can cheat spot checks by pattern-matching templates.
- **Fix:** Use LLM-generated dynamic spot checks (noted as TODO in CLAUDE.md).

### M4. Nonce Management Not Atomic
- **File:** `agent_market/chain.py:85`, `agent_market/commerce.py:89`, `agent_market/registry.py:79`
- **Issue:** `get_transaction_count()` is called to get the nonce, but under concurrent requests, two transactions can get the same nonce. The `_onchain_lock` in server.py helps but only for commerce calls, not for registry or scorer calls.
- **Fix:** Use a centralized nonce manager or queue all on-chain transactions through the same lock.

### M5. `_cached_workers` is a Class Variable (Shared Across Instances)
- **File:** `agent_market/registry.py:99-100`
- **Issue:** `_cached_workers: List[Dict] = []` and `_cache_time: float = 0` are class-level attributes, not instance-level. If multiple `RegistryClient` instances exist, they share cache state. Not a bug currently (only one instance), but fragile.
- **Fix:** Move to `__init__`.

### M6. `getActiveMinerCount()` is O(n) On-Chain
- **File:** `contracts/MinerRegistry.sol:75-79`
- **Issue:** `getActiveMinerCount()` iterates over all miners in a loop. As the registry grows, this becomes expensive and may hit gas limits for view calls.
- **Fix:** Maintain an `activeMinerCount` counter that's updated on register/deactivate.

### M7. AgenticCommerceV2 `submit()` Allows Anyone to Be Provider
- **File:** `contracts/AgenticCommerceV2.sol:106-116`
- **Issue:** Any address can call `submit()` on a funded job. There's no whitelist or approval process. First submitter becomes the provider.
- **Impact:** Front-running — a bot can watch for funded jobs and submit a garbage deliverable hash before the intended worker.
- **Fix:** Add a provider assignment step, or require the evaluator to approve the provider.

### M8. No Input Length Limits on Registration
- **File:** `agent_market/api/server.py:1337-1398`
- **Issue:** `/register` accepts any length `agent_name` and `wallet_address`. A malicious client could submit a 1MB agent name.
- **Fix:** Add `max_length` constraints to the fields.

### M9. `_register_rate_limit` Memory Leak
- **File:** `agent_market/api/server.py:1335`
- **Issue:** `_register_rate_limit: dict = {}` grows unboundedly — every unique IP that registers is stored forever.
- **Fix:** Periodically clean up entries older than 1 hour, or use an LRU cache.

### M10. Scoring Weights Don't Sum to 1.0 in All Paths
- **File:** `agent_market/manager/scorer.py:46-70`
- **Issue:** When `is_spot_check=True` but `all_responses` is empty, the score is: `0.60 * spot_check + 0.10 * format + 0.05 * speed = 0.75 max`. The missing 0.25 (consensus weight) means spot-check-only scores are capped at 0.75, which is barely above the 0.70 quality gate.
- **Fix:** Redistribute weights when consensus is unavailable.

### M11. `Dockerfile.worker` References Old Module Name
- **File:** `Dockerfile.worker:15`
- **Issue:** CMD runs `agents.miner_agent` but the module was renamed to `agents.worker_agent`. The Dockerfile hasn't been updated.
- **Fix:** Change to `agents.worker_agent`.

### M12. No HTTPS Enforcement
- **File:** `agent_market/api/server.py`
- **Issue:** No TLS/HTTPS enforcement. Worker endpoints registered over HTTP transmit API keys and verification data in plaintext.
- **Fix:** Validate that registered worker endpoints use HTTPS.

### M13. `last_used_at` Set to String "now()"
- **File:** `agent_market/keys.py:178`
- **Issue:** `"last_used_at": "now()"` — this is a string literal, not a SQL function call. PostgREST doesn't interpret SQL functions in PATCH payloads. The field gets set to the literal string "now()".
- **Fix:** Use `datetime.now(timezone.utc).isoformat()` instead.

### M14. Frontend `agentId` URL Parameter Not Sanitized
- **File:** `web/app/agent/[agentId]/page.tsx`
- **Issue:** The `agentId` from the URL is used directly in fetch URLs without encoding. Special characters could break the API call or enable injection.
- **Fix:** Use `encodeURIComponent(agentId)`.

### M15. Silent Error Swallowing Throughout
- **Files:** Multiple (server.py:86, jobs/page.tsx, leaderboard/page.tsx, etc.)
- **Issue:** Empty `catch {}` blocks appear 10+ times across the codebase. Errors are silently ignored, making debugging impossible.
- **Fix:** At minimum, log the error. Don't use empty catch blocks.

### M16. `ChainScorer` Comment Says "Base Sepolia" But Deploys to Mainnet
- **File:** `agent_market/chain.py:21`
- **Issue:** Class docstring says "Write scores to AgentScorer.sol on Base Sepolia" but the contract is deployed on Base Mainnet.
- **Fix:** Update the docstring.

### M17. No Pagination on `/jobs/list` and `/agents`
- **File:** `agent_market/api/server.py:1180-1223,1299-1332`
- **Issue:** `/jobs/list` reads up to 50 jobs from chain in a loop of synchronous RPC calls. `/agents` reads all agents. Both can become very slow as the registry grows.
- **Fix:** Add pagination parameters and limit results.

### M18. Test Coverage Gaps
- **File:** `tests/`
- **Issue:** Only 3 test files covering analyzer, scorer, and x402. No tests for:
  - `server.py` endpoints (registration, claim, submit, withdraw, faucet)
  - `commerce.py` (job creation, completion)
  - `registry.py` (worker registration)
  - `token.py` (transfers, faucet)
  - Concurrent access patterns
  - Frontend components
- **Fix:** Add integration tests for all API endpoints with TestClient.

---

## LOW FINDINGS (8)

### L1. Backward-Compatible Aliases Add Confusion
- **Files:** `protocol.py:54-55`, `scorer.py:289`, `spot_check.py:335`, `registry.py:139`
- **Issue:** Old names (`CodeVerificationRequest`, `MinerScorer`, `HoneypotGenerator`, `get_active_miners`) are aliased but not documented as deprecated.

### L2. `layout 2.tsx` Is a Duplicate File
- **File:** `web/app/layout 2.tsx`
- **Issue:** Likely an accidental copy. Should be deleted.

### L3. Dead `AgenticCommerce.sol` (V1) Still in Repo
- **File:** `contracts/AgenticCommerce.sol`
- **Issue:** V1 contract is superseded by V2 but still present.

### L4. `_supabase_request` Doesn't Retry on Transient Failures
- **File:** `agent_market/keys.py:32-57`
- **Issue:** Single attempt with 10s timeout. Transient network errors cause silent failures.

### L5. `results` Dict Grows Unboundedly
- **File:** `agent_market/api/server.py:80`
- **Issue:** Every verification result is stored in `results = {}` forever. Memory leak over time.

### L6. Image Spot Check `_make_noise_png` Uses `random` (Not Cryptographic)
- **File:** `agent_market/manager/image_spot_check.py:224`
- **Issue:** `random.randint()` is predictable with a known seed. Not a security issue for spot checks, but noted.

### L7. `pyproject.toml` Doesn't Pin Dependency Versions
- **File:** `pyproject.toml:11-14`
- **Issue:** `fastapi`, `uvicorn` unpinned. A breaking update could break the build.

### L8. No Health Check Interval for Registered Workers
- **Issue:** Workers are registered once and never health-checked again. A dead worker stays in the registry until manually removed.

---

## SMART CONTRACT SUMMARY

| Contract | Severity | Notes |
|----------|----------|-------|
| AgentScorer | HIGH | Owner-only, no ownership transfer, centralized |
| AgenticCommerceV2 | MEDIUM | Reentrancy pattern (mitigated by state), no expiry, open submit |
| MinerRegistry | MEDIUM | No admin deactivation, O(n) active count |
| ProtocolCredits | HIGH | Unlimited minting via faucet, no supply cap |
| AgenticCommerce (V1) | LOW | Dead code, superseded by V2 |

---

## ARCHITECTURE ASSESSMENT

**Strengths:**
- Clean role separation (client/worker/manager)
- Graceful degradation — everything works without chain
- Spot check mechanism is genuinely novel
- Three-layer architecture (API/Supabase/Chain) is sound
- Consensus F1 scoring is well-implemented

**Weaknesses:**
- Sequential worker calls (should be parallel)
- In-memory state for critical data
- No worker authentication enables Sybil attacks
- Static spot check templates are gameable
- Single manager = single point of failure

---

## TOP 5 ACTIONS BEFORE PRODUCTION

1. **Remove all hardcoded secrets** (C1, C2) — Supabase key, Alchemy key
2. **Fix race conditions** (C3, C4) — atomic credit deduction, atomic job claims
3. **Add worker authentication** (C5) — require API key or on-chain stake for registration
4. **Add ReentrancyGuard to contracts** (C6) — and add job expiry mechanism (H11)
5. **Restrict CORS** (H4) — and add rate limiting to faucet (H2)

---

*Audit complete. 45 total findings: 7 critical, 12 high, 18 medium, 8 low.*

================================================================
## FRONTEND
================================================================
## OUTBOX

# COMPLETE AUDIT REPORT — Agent Labor Market
**Auditor:** Claude Opus 4.6 (Independent)
**Date:** 2026-03-31
**Branch:** `feature/enforce-role-separation`
**Scope:** All files in `agent_market/`, `contracts/`, `tests/`, `web/app/`, config files

---

## CRITICAL FINDINGS (Must Fix Before Production)

### C1. PRIVATE KEY COMMITTED TO REPOSITORY
- **File:** `.env.eigencompute` line 4
- **Finding:** `PRIVATE_KEY=0x6ee34123f6a3ff1abfa90e64ebb5bb0eaf92d2ed012fce2ed3da7d6082a80858`
- **Impact:** Anyone with repo access can drain the wallet. This key controls on-chain scoring, job creation, token transfers, and registry operations.
- **Fix:** Rotate the key immediately. Add `.env*` to `.gitignore`. Use a secrets manager (Railway env vars, etc).

### C2. SUPABASE ANON KEY HARDCODED IN SOURCE
- **File:** `agent_market/keys.py` lines 27-28
- **Finding:** `SUPABASE_URL` and `SUPABASE_KEY` are hardcoded as defaults. The anon key is visible: `eyJhbGci...`. Combined with the URL, anyone can query all tables with anon-level RLS.
- **Impact:** If RLS policies are misconfigured, all API keys, usage logs, registered workers, and completed jobs are exposed.
- **Fix:** Remove hardcoded defaults. Require env vars. Audit Supabase RLS policies for every table.

### C3. ALCHEMY API KEY HARDCODED IN SOURCE
- **File:** `agent_market/x402.py` line 160, `agent_market/erc8004.py` line 21
- **Finding:** `https://base-mainnet.g.alchemy.com/v2/VkqT8RyCceRMz0G4PbTQYJjkG5KMFIQZ` hardcoded as default RPC URL.
- **Impact:** Key abuse, rate limiting, cost to project.
- **Fix:** Move to env var, remove from source.

### C4. REENTRANCY IN AgenticCommerceV2.sol `complete()`
- **File:** `contracts/AgenticCommerceV2.sol` lines 119-137
- **Finding:** State is changed (`job.state = State.Completed`) before ETH transfers via `_transfer()` which uses `to.call{value: amount}("")`. However, the fee transfer to `feeRecipient` happens first (line 130), then payout to `provider` (line 133). If `feeRecipient` is a malicious contract, it could reenter `complete()` — but the state check (`require job.state == Submitted`) would block it. The `provider` payout is more dangerous: a malicious provider contract could reenter other functions (e.g., `fund()` on a different job).
- **Severity:** Medium-High. Classic checks-effects-interactions violation. The state update protects against same-job reentrancy, but cross-function reentrancy is possible.
- **Fix:** Use ReentrancyGuard from OpenZeppelin, or move `_transfer` calls after all state updates, or use pull-payment pattern.

### C5. RACE CONDITION IN CREDIT DEDUCTION (TOCTOU)
- **File:** `agent_market/keys.py` lines 155-188 (`use_credit`)
- **Finding:** Credit check (line 170-171) and credit decrement (line 175-178) are two separate HTTP requests to Supabase. Under concurrent requests, two calls could both read `credits_remaining = 1`, both pass the check, and both decrement — resulting in negative credits (free service).
- **Impact:** Clients can bypass the credit system by sending parallel requests.
- **Fix:** Use a Supabase RPC function with `UPDATE ... SET credits_remaining = credits_remaining - 1 WHERE credits_remaining > 0 RETURNING credits_remaining` as an atomic operation.

### C6. NO INPUT SANITIZATION ON SUPABASE QUERIES
- **File:** `agent_market/keys.py` lines 141, 170, 195; `agent_market/api/server.py` lines 929, 1021, 1549
- **Finding:** User-supplied values (agent_id, task_id, agent_name) are interpolated directly into Supabase REST API URL query parameters (e.g., `f"api_keys?agent_name=eq.{agent_name}"`). PostgREST is mostly safe against SQL injection, but special characters in agent_name (e.g., `&`, `=`) could corrupt the query URL.
- **Fix:** URL-encode all user-supplied values with `urllib.parse.quote()`.

### C7. OPEN CORS POLICY
- **File:** `agent_market/api/server.py` lines 46-51
- **Finding:** `allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]`. Any website can make authenticated requests on behalf of users who have API keys stored in their browser.
- **Impact:** CSRF-like attacks. A malicious site could call `/withdraw` with a victim's API key if they have it in a cookie or local storage.
- **Fix:** Restrict origins to known domains (the frontend domain, `localhost` for dev).

---

## HIGH FINDINGS

### H1. FAUCET HAS NO RATE LIMIT (ON-CHAIN DRAIN)
- **File:** `agent_market/api/server.py` lines 1413-1434 (`/faucet`)
- **Finding:** The faucet endpoint has no rate limiting. While the on-chain `ProtocolCredits.faucet()` has a cooldown per address, the server's `/faucet` endpoint uses `_token.transfer()` (line 89-93 of token.py) — transferring from the manager's wallet, NOT calling the on-chain faucet function. So the on-chain cooldown is bypassed. Anyone can call `/faucet` repeatedly with different addresses and drain the manager's AVNC balance.
- **Fix:** Either call the on-chain `faucet()` function instead of `transfer()`, or add rate limiting (per IP, per address) and a maximum total distribution cap.

### H2. WITHDRAWAL ENDPOINT LACKS IDEMPOTENCY PROTECTION
- **File:** `agent_market/api/server.py` lines 1582-1646 (`/withdraw`)
- **Finding:** If the Supabase PATCH to zero out earnings (line 1634) fails after the on-chain transfer succeeds (line 1619), the user retains their balance and can withdraw again — double-spend.
- **Fix:** Zero out earnings BEFORE sending the on-chain transfer. If transfer fails, restore the balance.

### H3. NONCE CONFLICTS IN CONCURRENT ON-CHAIN TRANSACTIONS
- **File:** `agent_market/api/server.py` line 74, `agent_market/token.py`, `agent_market/commerce.py`, `agent_market/chain.py`
- **Finding:** The `_onchain_lock` (threading.Lock) only protects the commerce+scorer operations in `_process_onchain_background`. But `_token.transfer()` (called from `/faucet` and `/withdraw`), `_registry.register_worker()`, and `_erc8004.publish_reputation()` all build transactions with `get_transaction_count()` independently, without the lock. Concurrent on-chain calls will get the same nonce and one will fail.
- **Fix:** Use a single global nonce lock for ALL on-chain transactions, or use a nonce manager.

### H4. WORKER ENDPOINT SSRF VIA REGISTRATION
- **File:** `agent_market/api/server.py` lines 582-675 (`/register-worker`)
- **Finding:** When registering, the server makes an HTTP request to `request.endpoint + "/health"` (line 592). An attacker can register `endpoint=http://169.254.169.254/latest/meta-data` or internal services, using the server as an SSRF proxy. The health check response is not validated beyond status code.
- **Fix:** Validate that the endpoint is a public URL (not RFC 1918 ranges, link-local, localhost). Use allowlists.

### H5. NO AUTHENTICATION ON SENSITIVE ENDPOINTS
- **File:** `agent_market/api/server.py`
- **Finding:** These endpoints require no auth: `/leaderboard`, `/network`, `/agents`, `/activity`, `/stats`, `/jobs/marketplace`, `/protocol`. While read-only, `/protocol` (line 1453) returns full contract ABIs — not sensitive but verbose. More importantly, `/register-worker` and `/register-manager` require no auth — anyone can register arbitrary endpoints.
- **Impact:** Spam registrations, fake agents, misleading leaderboard.
- **Fix:** Require API key for registration. Add rate limiting.

### H6. ChainScorer REPORTS "base-sepolia" WHILE RUNNING ON MAINNET
- **File:** `agent_market/chain.py` line 98
- **Finding:** The `record_score` result dict hardcodes `"chain": "base-sepolia"` regardless of actual chain. The `chain_id` field is correctly set from deployed.json (line 56), but the human-readable string is always wrong for mainnet.
- **Fix:** Use conditional like commerce.py does: `"base-mainnet" if self.chain_id == 8453 else "base-sepolia"`.

---

## MEDIUM FINDINGS

### M1. ProtocolCredits.sol UNLIMITED MINTING IN FAUCET
- **File:** `contracts/ProtocolCredits.sol` lines 37-45
- **Finding:** The `faucet()` function calls `_mint()`, creating new tokens. There's no cap on total supply. Anyone can claim 20 AVNC per day, inflating supply infinitely. With enough addresses, supply grows without bound.
- **Fix:** Add a `maxSupply` cap, or use a fixed pool instead of minting.

### M2. AgenticCommerceV2.sol NO JOB EXPIRY MECHANISM
- **File:** `contracts/AgenticCommerceV2.sol`
- **Finding:** Jobs can be created and funded but never expire. If an evaluator disappears, client funds are locked forever. The `Expired` state exists in the enum but no function transitions to it.
- **Fix:** Add a `expire()` function callable after a timeout (e.g., 30 days), refunding the client.

### M3. MinerRegistry.sol getActiveMinerCount() IS O(n)
- **File:** `contracts/MinerRegistry.sol` lines 75-79
- **Finding:** Iterates all miners to count active ones. Gas cost grows linearly. At 10,000 miners this would be very expensive to call on-chain.
- **Fix:** Track `activeMinerCount` as a storage variable, increment/decrement on register/deactivate.

### M4. ANYONE CAN SUBMIT TO ANY FUNDED JOB
- **File:** `contracts/AgenticCommerceV2.sol` lines 106-116
- **Finding:** `submit()` has no access control on who can be the provider. Any address can submit a deliverable hash to any funded job. First submitter wins.
- **Impact:** Front-running. A bot could watch for funded jobs and submit garbage deliverables.
- **Fix:** Add an assignment step, or require the evaluator to approve the provider before submission.

### M5. DEAD CONSENSUS SCORING IN NETWORK MODE
- **File:** `agent_market/api/server.py` lines 430-454
- **Finding:** Network mode creates `_R` helper objects (line 437-439) with only an `issues` attribute for consensus scoring. But `WorkerScorer._score_consensus_f1` accesses `resp.issues` which works. However, without spot checks in network mode, the scorer only scores format (10%) + speed (5%) + partial consensus credit (10%) = max ~25% for solo workers. Solo workers can never pass the quality gate (0.70).
- **Impact:** Solo workers always fail the quality gate in scoring, though this doesn't currently block the response (gate not enforced in network mode). But if gate enforcement is added, the system breaks with < 2 workers.

### M6. LOGGER FILE WRITE RACE CONDITION
- **File:** `agent_market/logger.py` lines 17-51
- **Finding:** `_load_log()` and `_save_log()` read/write `agent_log.json` without file locking. Concurrent requests will corrupt the JSON file.
- **Fix:** Use `filelock` or `fcntl.flock`, or switch to append-only logging (one JSON line per event).

### M7. IN-MEMORY STATE LOST ON RESTART
- **File:** `agent_market/api/server.py` lines 80-81
- **Finding:** `results = {}` and `_registered_workers` are in-memory. Workers loaded from Supabase on startup (good), but all verification results are lost on restart. `/status/{task_id}` will 404 for all prior tasks.
- **Fix:** Persist results to Supabase, or document this limitation.

### M8. `_total_verifications` COUNTER NEVER INCREMENTED
- **File:** `agent_market/api/server.py` line 85
- **Finding:** `_total_verifications: int = 0` is declared but never incremented anywhere. The `/network` endpoint uses `len(results)` instead (line 748).
- **Fix:** Remove the unused variable.

### M9. DUPLICATE CSS AND LAYOUT FILES
- **File:** `web/app/globals 2.css`, `web/app/layout 2.tsx`
- **Finding:** Duplicate files with spaces in names. Likely accidental copies.
- **Fix:** Remove duplicates.

---

## LOW FINDINGS

### L1. MISSING HONEYPOT.PY FILE (IMPORT WILL FAIL)
- **File:** `agent_market/manager/forward.py` line 20
- **Finding:** Imports `from agent_market.manager.spot_check import SpotCheckGenerator` — file exists as `spot_check.py`. But CLAUDE.md references `honeypot.py` as the spot check file. The actual import is correct, but the rename from `honeypot.py` to `spot_check.py` may be incomplete in some paths.
- **Verified:** The import works. This is a documentation discrepancy only.

### L2. BACKWARD-COMPATIBLE ALIASES ADD CONFUSION
- **Files:** `agent_market/protocol.py` lines 54-55, `agent_market/manager/scorer.py` line 289, `agent_market/manager/spot_check.py` line 335, `agent_market/registry.py` lines 139-140
- **Finding:** `CodeVerificationRequest = JobRequest`, `MinerScorer = WorkerScorer`, `HoneypotGenerator = SpotCheckGenerator`, `get_active_miners = get_active_workers`. These exist for backward compatibility but add confusion.
- **Fix:** Search for usages; if none, remove aliases.

### L3. TEST COVERAGE GAPS
- **File:** `tests/`
- **Finding:** No tests for: `/register`, `/faucet`, `/withdraw`, `/jobs/create`, `/jobs/claim`, `/jobs/submit`, consensus scoring, on-chain integration, text analyzer. Only 3 test files covering code analysis, x402, and image analysis.
- **Fix:** Add integration tests for the complete API surface.

### L4. FIELD NAME INCONSISTENCY: task_type vs job_type
- **File:** `agent_market/protocol.py` line 23
- **Finding:** The field is named `task_type` with alias `job_type`. CLAUDE.md says "job not task everywhere." The VerifyRequest model (server.py line 195) uses `task_type` without alias.
- **Fix:** Complete the rename to `job_type` as primary field name.

### L5. `registered_miners` TABLE IN SUPABASE
- **File:** `agent_market/api/server.py` line 699
- **Finding:** `/register-manager` writes to `registered_miners` table (old name), while `/register-worker` writes to `registered_workers` table (new name). The manager registration still uses the old table name.
- **Fix:** Migrate to consistent table naming.

### L6. NO PAGINATION ON SUPABASE QUERIES
- **File:** `agent_market/api/server.py` lines 548, 868
- **Finding:** Leaderboard reads ALL completed_jobs without limit. Marketplace reads last 50 jobs. As data grows, the leaderboard query will become slow and potentially hit Supabase's row limit.
- **Fix:** Add `&limit=1000` or aggregate server-side.

---

## SMART CONTRACT AUDIT SUMMARY

| Contract | Finding | Severity |
|----------|---------|----------|
| AgenticCommerceV2 | Reentrancy in `complete()` — ETH sent before all state finalized | High |
| AgenticCommerceV2 | No job expiry — funds locked if evaluator vanishes | Medium |
| AgenticCommerceV2 | Anyone can `submit()` to any funded job — front-running | Medium |
| AgenticCommerceV2 | `createJob` with `budget=1 wei` is valid — dust jobs clog the contract | Low |
| ProtocolCredits | Unlimited minting via `faucet()` — no supply cap | Medium |
| ProtocolCredits | No `burn()` function — deflation impossible | Low |
| MinerRegistry | `getActiveMinerCount()` is O(n) — gas scales linearly | Medium |
| MinerRegistry | No re-activation function — deactivated agents must re-register | Low |
| AgentScorer | Only owner can record scores — centralized trust | By design |
| AgentScorer | Scores array grows unbounded — reading old scores costs more gas over time | Low |

---

## ARCHITECTURE ASSESSMENT

### Strengths
1. **Clean role separation** — Manager never does analysis work. Workers never score. Enforced in code.
2. **Graceful degradation** — System works without chain, without LLM, without Supabase. Every dependency is optional.
3. **Spot check mechanism** — Genuine innovation. No competitor has automated, objective quality measurement in decentralized agent markets.
4. **Multiple payment paths** — Free tier, x402, on-chain escrow, faucet. Low friction onboarding.
5. **Consensus F1 scoring** — Well-designed issue-level F1 metric with canonicalization.

### Weaknesses
1. **Single manager = single point of failure** — The manager wallet controls scoring, job creation, and payment. Compromise = total control.
2. **Static spot check templates** — 12 bug templates + 2 clean. Workers can memorize them. Dynamic randomization helps but patterns are recognizable.
3. **No dispute resolution** — If evaluator rejects work unfairly, provider has no recourse.
4. **Credit system is off-chain** — The real economic incentives are in Supabase (earnings, credits), not on-chain. Supabase admin can modify balances.
5. **Blocking HTTP calls to workers** — `urllib.request.urlopen` with 30s timeout in the request path. A slow/malicious worker blocks the response for all clients.

---

## PERFORMANCE CONCERNS

1. **Synchronous worker fan-out** — Server queries workers sequentially (server.py lines 399-427). With 10 workers at 5s each = 50s response time. Should use asyncio.gather.
2. **On-chain reads in request path** — `/jobs/marketplace` reads on-chain state for each job (lines 874-884). 50 jobs = 50 RPC calls per request.
3. **JSON file logger** — `agent_log.json` is read/written on every event. Grows unbounded. Will eventually cause I/O bottleneck.
4. **Registry cache is class-level** — `RegistryClient._cached_workers` and `_cache_time` are class variables, not instance variables (registry.py lines 99-100). Works because there's one instance, but could cause issues if multiple instances are created.

---

## RECOMMENDATIONS (Priority Order)

1. **IMMEDIATE:** Rotate the committed private key. Remove all hardcoded secrets from source.
2. **IMMEDIATE:** Add `.env*` to `.gitignore`.
3. **BEFORE PRODUCTION:** Fix reentrancy in AgenticCommerceV2 (add ReentrancyGuard).
4. **BEFORE PRODUCTION:** Fix TOCTOU race in credit deduction (atomic Supabase operation).
5. **BEFORE PRODUCTION:** Fix faucet drain vulnerability (rate limit + cap).
6. **BEFORE PRODUCTION:** Fix withdrawal double-spend (debit before transfer).
7. **BEFORE PRODUCTION:** Add nonce management for concurrent on-chain txs.
8. **BEFORE PRODUCTION:** Restrict CORS origins.
9. **BEFORE PRODUCTION:** Add SSRF protection to worker registration.
10. **SHORT TERM:** Add job expiry to AgenticCommerceV2.
11. **SHORT TERM:** Add supply cap to ProtocolCredits.
12. **SHORT TERM:** Switch to async worker fan-out.
13. **SHORT TERM:** Expand test coverage to all endpoints.
14. **MEDIUM TERM:** Dynamic LLM-generated spot checks.
15. **MEDIUM TERM:** Dispute resolution mechanism.

---

**Total findings:** 7 Critical, 6 High, 9 Medium, 6 Low
**Production readiness:** NOT READY — Critical secrets exposure and financial vulnerabilities must be fixed first.

================================================================
## DESIGNER
================================================================
## OUTBOX

# COMPLETE AUDIT REPORT — Agent Labor Market
**Date:** 2026-03-31
**Branch:** `feature/enforce-role-separation`
**Auditor:** Claude Opus 4.6 (independent, consensus mode)
**Scope:** All Python, Solidity, TypeScript, configs, tests, Docker

---

## EXECUTIVE SUMMARY

**Verdict: NOT PRODUCTION-READY.** 8 critical findings, 16 high-severity findings, and 20+ medium/low issues. The most dangerous: payment bypass (x402), unlimited token inflation (AVNC faucet), hardcoded secrets, zero role-based access control, and SSRF. The spot check mechanism (the project's moat) is gameable with only 12+7 templates. Consensus scoring is dead code. Fix the criticals before any mainnet traffic.

---

## CRITICAL FINDINGS (8)

### C1. Transaction Hash Replay — Unlimited Free Verifications
**File:** `agent_market/x402.py:153`
A valid `txHash` can be reused across unlimited requests. No tracking of spent tx hashes. Attacker pays once, gets infinite verifications.
**Fix:** Maintain a set of consumed tx hashes in Supabase. Reject duplicates.

### C2. AVNC Payment Amount Not Verified
**File:** `agent_market/x402.py:193-198`
The x402 AVNC verification checks that a `Transfer` event exists to the correct recipient but **never checks the amount**. Attacker sends 1 wei of AVNC, passes verification.
**Fix:** Compare `event.args.value` against `min_price_wei`.

### C3. Credit Deduction TOCTOU Race — Unlimited Free API Usage
**File:** `agent_market/keys.py:155-188`
`use_credit()` reads `credits_remaining`, checks > 0, then PATCHes separately. Two concurrent requests both read `credits_remaining=1`, both pass, both decrement. Result: `credits_remaining=-1`. Unlimited free usage with concurrent requests.
**Fix:** Use Supabase RPC: `UPDATE api_keys SET credits_remaining = credits_remaining - 1 WHERE credits_remaining > 0 RETURNING *`.

### C4. Hardcoded Alchemy API Key in Source
**Files:** `agent_market/x402.py:161`, `agent_market/erc8004.py:22`
Full Alchemy API key `VkqT8RyCceRMz0G4PbTQYJjkG5KMFIQZ` committed to source. Anyone with repo access gets free RPC access. Can be rate-limited or abused.
**Fix:** Rotate immediately. Move to env var with no hardcoded fallback.

### C5. Private Key on Disk in Plaintext
**File:** `.env.eigencompute` (untracked but on disk)
`PRIVATE_KEY=0x6ee341...` controls on-chain tx signing (score recording, token transfers). Filesystem access = full key compromise.
**Fix:** Rotate key. Use a secrets manager.

### C6. Unlimited AVNC Token Inflation via Faucet
**File:** `contracts/ProtocolCredits.sol:37-45`
`faucet()` mints new tokens with no total supply cap. Any address can claim 20 AVNC/day. Create unlimited wallets = unlimited AVNC. Destroys token economics if AVNC is used for escrow payments.
**Fix:** Add `maxSupply` cap. Restrict faucet to registered agents. Add `require(cooldown >= 1 hours)` on `setFaucetCooldown()`.

### C7. Fail-Open on Analysis Error — Crash = Clean Verdict
**File:** `agent_market/worker/forward.py:69-78`
Any exception during analysis returns `passed=True, confidence=0.0, issues=[]`. OOM, timeout, or malformed input → malicious code gets a clean bill of health.
**Fix:** Change to `passed=False` in the error path.

### C8. No Role Separation — Anyone Can Do Everything
**File:** `agent_market/api/server.py` (throughout)
Zero role enforcement:
- Worker API keys can call `/jobs/create` (client action)
- Clients can register as workers
- `/jobs/{task_id}/submit` doesn't verify submitter == claimer. Any API key holder submits results and collects 85% payment
- `/jobs/create` has an unauthenticated code path (line 804 falls through if no key)
**Fix:** Add `role` field to API keys. Enforce role checks per endpoint. Verify submitter matches `claimed_by`.

---

## HIGH FINDINGS (16)

### H1. Supabase Anon Key Hardcoded
**File:** `agent_market/keys.py:28`
Full JWT hardcoded as default. If RLS not configured on all tables, attackers can read/write all API key data, earnings, job records.

### H2. Supabase Query Injection via URL Params
**Files:** `agent_market/keys.py:195`, `agent_market/api/server.py:929,1550`
`agent_id` interpolated directly into PostgREST URL. `agent_id=foo&select=*` alters query. `task_id` never validated as UUID.
**Fix:** URL-encode all interpolated values. Validate UUID format.

### H3. No Auth on Worker/Manager Registration
**File:** `agent_market/api/server.py:582,678`
Zero authentication. Flood registry with fake workers to dominate consensus. Overwrite existing worker's endpoint by re-registering same `agent_id` (identity hijacking, line 624).

### H4. SSRF via Worker Endpoint + Agent Health Proxy
**Files:** `server.py:593,411,1496`, `manager/forward.py:256`
User-supplied endpoint URL hit with `urllib.request.urlopen`. Register `endpoint: http://169.254.169.254/latest/meta-data/` → cloud metadata exfiltration. `/agent-health/{agent_id}` is an open SSRF proxy.

### H5. CORS Wildcard with API Key Auth
**File:** `agent_market/api/server.py:46-51`
`allow_origins=["*"]` + `allow_methods=["*"]` + `allow_headers=["*"]`. Any website can make authenticated cross-origin requests.

### H6. No Faucet Rate Limiting (Off-Chain)
**Files:** `agent_market/token.py:77-118`, `agent_market/api/server.py:1413`
No per-wallet cooldown, no auth, no cap. Drain faucet by calling repeatedly.

### H7. Spot Checks Gameable — Tiny Template Pool
**Files:** `agent_market/manager/spot_check.py` (12 templates), `agent_market/manager/image_spot_check.py` (7 templates)
Workers can fingerprint by intent string, AST structure, or image dimensions. Image spot checks generated once at import time (same data every round). Clean code templates (factorial, reverse_string) are trivially recognizable.
**Fix:** LLM-generated dynamic spot checks. 50+ templates. Randomize intents. Generate images fresh per round.

### H8. Score Read/Write Mismatch (Data Corruption)
**File:** `agent_market/erc8004.py:153-154,210`
Writes `int(score * 10000)` with `value_decimals=2`. Read path: `value / 10^decimals` = `9500/100 = 95.0` instead of `0.95`. All on-chain reputation scores are 100x inflated.

### H9. Nonce Race Condition (Systemic)
**Files:** `chain.py:82`, `commerce.py:85`, `registry.py:73`, `token.py:89`, `erc8004.py:160`
Every tx-sending file calls `get_transaction_count()` independently. Concurrent txs get same nonce → one fails.
**Fix:** Centralized nonce manager with mutex.

### H10. Front-Running Griefing on Commerce Contract
**File:** `contracts/AgenticCommerceV2.sol:106-116`
Any address can `submit()` to any funded job. First caller becomes provider. Bot front-runs legitimate submissions with garbage. Evaluator rejects, but client must create a new job.

### H11. No Expiry — Permanent Fund Lock
**File:** `contracts/AgenticCommerceV2.sol`
`State.Expired` exists but no expiry function or timestamp. Funded jobs with no submission = ETH/tokens locked forever.

### H12. Race Condition on Job Claims
**File:** `agent_market/api/server.py:949-976`
Non-atomic read-check-write against Supabase. Two workers claim simultaneously, second overwrites first.

### H13. Race Condition on Earnings Credit
**File:** `agent_market/api/server.py:1148-1156`
Read current earnings → add share → write back. Concurrent submissions = lost updates.

### H14. Fee-on-Transfer Token Drain
**Files:** `contracts/AgenticCommerceV2.sol:96`, `contracts/AgenticCommerce.sol:70`
Assumes `transferFrom` delivers exact amount. Fee-on-transfer tokens deliver less, contract tries to send full amount → drains other users' funds.

### H15. Irreversible Deactivation in MinerRegistry
**File:** `contracts/MinerRegistry.sol:58-67`
`deactivate()` is permanent. No `reactivate()`. Can't re-register (index still exists). Accidental deactivation = permanent exclusion.

### H16. LLM API Key in Unignored .env
**File:** `.env.bankr-miner` (not in .gitignore)
`LLM_API_KEY=bk_62TKUEVQ...` could be accidentally committed with `git add .`.

---

## MEDIUM FINDINGS (20)

| # | Finding | File |
|---|---------|------|
| M1 | Timing attack on internal API key (`==` not `hmac.compare_digest`) | `keys.py:129` |
| M2 | `total_used` always set to 1, never incremented | `keys.py:175-178` |
| M3 | `last_used_at: "now()"` written as literal string, not timestamp | `keys.py:178` |
| M4 | Blocking `urllib` in async context (event loop starvation) | `storage.py:21`, `manager/forward.py:242-276`, `server.py:399-419` |
| M5 | Log file concurrent write data loss (no locking) | `logger.py:18-25` |
| M6 | Unbounded log growth (JSON file grows forever) | `logger.py:18-25` |
| M7 | Float-to-int score with no bounds check (negative → underflow) | `chain.py:76` |
| M8 | Hardcoded `"base-sepolia"` in result dict on mainnet | `chain.py:96` |
| M9 | Scoring too generous: substring type matching, 2-keyword threshold | `scorer.py:108-117` |
| M10 | Solo real jobs always fail quality gate (max 0.25 without consensus) | `scorer.py` |
| M11 | Free 0.10 consensus score when `all_responses` empty | `scorer.py:59-61` |
| M12 | Consensus gameable by colluding workers (F1 rewards majority) | `scorer.py:139-200` |
| M13 | Worker routing by name substring ("image"/"vision" in agent_id) | `manager/forward.py:228-235` |
| M14 | Retroactive fee changes on in-flight escrow jobs | `AgenticCommerceV2.sol:168-172` |
| M15 | `getActiveMinerCount()` O(n) unbounded loop → gas DoS on read | `MinerRegistry.sol:75-79` |
| M16 | No score validation bounds on-chain (can record 999999999) | `AgentScorer.sol:39-44` |
| M17 | No emergency pause on any contract | All contracts |
| M18 | Docker containers run as root, broken CMD in Dockerfile.worker | `Dockerfile.worker` |
| M19 | `dangerouslySetInnerHTML` in layout (latent XSS surface) | `web/app/layout.tsx:31-38` |
| M20 | `javascript:` URL possible in agent endpoint href | `web/app/agent/[agentId]/page.tsx:215` |

---

## LOW / INFO FINDINGS (12)

| # | Finding | File |
|---|---------|------|
| L1 | In-memory state loss on restart (rate limits, results, managers) | `server.py:80-84` |
| L2 | Error messages leak internal details to clients | `server.py:1222,1398,1541` |
| L3 | No input length validation on code/text/image/intent | `server.py:189-196` |
| L4 | `task_queue.pop(0)` is O(n), use `collections.deque` | `manager/forward.py:91` |
| L5 | New workers start EMA at 0.0 (unfair cold start) | `manager/forward.py:51` |
| L6 | Incomplete .gitignore (missing `.env.bankr-miner`, `.env.eigencompute-miner`) | `.gitignore` |
| L7 | `args.miners` bug crashes manager agent (should be `args.workers`) | `agents/manager_agent.py:164,173` |
| L8 | No dependency pinning (unpinned pip installs in Dockerfiles) | `Dockerfile`, `Dockerfile.worker` |
| L9 | Hardcoded API URL in 7 frontend files (no env var) | All `web/app/` pages |
| L10 | No CSP/security headers in Next.js config | `web/next.config.ts` |
| L11 | No ownership transfer on any contract | All contracts |
| L12 | Wallet address validation: no checksum, allows zero address | `server.py:1598` |

---

## TEST COVERAGE GAPS

**What's tested:** Code analyzer (6 tests), spot checks (3), scorer (3), e2e pipeline (2), x402 payments (14), image verification (12). Total: ~40 tests.

**What's NOT tested:**
- API server endpoints (registration, faucet, job CRUD, leaderboard) — 0 tests
- Text analyzer — 0 tests
- Manager forward loop (core routing/scoring orchestration) — 0 tests
- On-chain clients (chain.py, commerce.py, registry.py, token.py) — 0 tests
- Security scenarios (SSRF, injection, replay, race conditions) — 0 tests
- Frontend — 0 tests (no test framework installed)

**Weak tests:**
- `test_verification.py:172` — assertion `score >= 0` always passes (tautology)
- `test_verification.py:24-27` — `not passed or syntax_error` too permissive

---

## ARCHITECTURE CONCERNS

1. **Consensus scoring is dead code.** `scorer.py` has F1 consensus logic but `forward.py` never passes `all_responses`. Wiring it up is documented as needed but hasn't happened.

2. **Single-manager architecture.** One manager is a SPOF. If it goes down, no jobs are routed. No manager-to-manager consensus or failover.

3. **No dispute mechanism.** On-chain evaluator has god-mode power per job (approve/reject unilaterally). No multi-sig, no timeout override, no arbitration.

4. **Incomplete rename.** `Dockerfile.worker` CMD still references `agents.miner_agent`. `become-a-miner/` and `become-a-validator/` directories still exist alongside the new names.

---

## PRIORITY REMEDIATION ORDER

**Before any production traffic:**
1. Fix C1 (tx replay) + C2 (AVNC amount check) — payment bypass
2. Fix C3 (credit TOCTOU) — free API abuse
3. Rotate C4 (Alchemy key) + C5 (private key) — secret exposure
4. Fix C7 (fail-open) — silent false negatives
5. Fix C8 (role separation) — authorization

**Before meaningful economic value:**
6. Fix C6 (faucet supply cap) — token inflation
7. Fix H8 (score decimals) — on-chain data corruption
8. Fix H9 (nonce manager) — tx reliability
9. Fix H3 (registration auth) — Sybil prevention
10. Fix H4 (SSRF) — network scanning

**Before scale:**
11. Wire up consensus scoring
12. Dynamic spot checks (50+ templates)
13. Async HTTP calls (replace urllib with httpx/aiohttp)
14. Persistent rate limiting
15. Input size limits

---

*End of audit report.*

================================================================
## RESEARCH
================================================================
## OUTBOX

# COMPLETE AUDIT REPORT: Agent Labor Market
**Date:** 2026-03-31
**Branch:** `feature/enforce-role-separation`
**Scope:** All Python backend, Solidity contracts, Next.js frontend, config, tests, CI/CD
**Auditor:** Independent automated audit (consensus mode, 3 agents)

---

## EXECUTIVE SUMMARY

**Verdict: NOT PRODUCTION-READY.** The codebase has 7 critical, 11 high, 14 medium, and 12+ low severity issues across backend, smart contracts, and frontend. The most dangerous findings are **hardcoded secrets in source code**, **reentrancy in commerce contracts**, **missing rate limiting**, and **unauthenticated worker registration**. All critical issues must be resolved before mainnet deployment with real funds.

| Category | CRITICAL | HIGH | MEDIUM | LOW |
|----------|----------|------|--------|-----|
| Backend (Python/FastAPI) | 4 | 5 | 6 | 7 |
| Smart Contracts (Solidity) | 5 | 8 | 9 | 5 |
| Frontend (Next.js) | 2 | 2 | 5 | 3 |
| Infrastructure/Config | 1 | 1 | 2 | 1 |
| **TOTAL** | **12** | **16** | **22** | **16** |

---

## SECTION 1: CRITICAL FINDINGS (Must Fix Immediately)

### C1: HARDCODED SECRETS IN SOURCE CODE
**Severity: CRITICAL | Files: `agent_market/keys.py:27-28`, `agent_market/erc8004.py:21`, `agent_market/x402.py:160`**

Supabase URL + JWT anon key hardcoded as defaults in `keys.py`:
```python
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://zdxisjihyfybnzwurjto.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
```

Alchemy RPC API key hardcoded in `erc8004.py` and `x402.py`:
```python
BASE_MAINNET_RPC = os.environ.get("BASE_RPC_URL", "https://base-mainnet.g.alchemy.com/v2/VkqT8RyCceRMz0G4PbTQYJjkG5KMFIQZ")
```

**Impact:** Anyone reading source can access Supabase DB (read/write API keys, agent records, job data) and abuse RPC endpoint.

**Fix:** Remove all defaults. Require env vars or crash on startup.

---

### C2: EXPOSED PRIVATE KEY IN .env FILES
**Severity: CRITICAL | Files: `.env.eigencompute`, `.env.bankr-miner`**

`.env.eigencompute` contains a raw private key:
```
PRIVATE_KEY=0x6ee34123f6a3ff1abfa90e64ebb5bb0eaf92d2ed012fce2ed3da7d6082a80858
```

`.env.bankr-miner` contains an API key:
```
LLM_API_KEY=bk_62TKUEVQZ77T975ZXYSA3RVEMS6DFGPE
```

**Impact:** Full wallet control. Fund theft. These files are untracked but present on disk.

**Fix:** Rotate all keys immediately. Add `.env*` to `.gitignore`. Never commit secrets.

---

### C3: REENTRANCY IN AgenticCommerceV2.sol complete()
**Severity: CRITICAL | File: `contracts/AgenticCommerceV2.sol:119-137`**

The `complete()` function makes two external ETH/token transfers after state change:
```solidity
job.state = State.Completed;
_transfer(job.token, feeRecipient, fee);   // External call 1
_transfer(job.token, job.provider, payout); // External call 2
```

If `feeRecipient` is a contract with a `receive()` fallback, it can re-enter `complete()` on the same jobId before the second transfer. State is already `Completed` but the second transfer hasn't happened yet — attacker can manipulate execution flow.

Same issue in `AgenticCommerce.sol:93-102` (v1).

**Fix:** Add `nonReentrant` modifier (OpenZeppelin ReentrancyGuard) or use pull-payment pattern.

---

### C4: NO OWNER TRANSFER ON ANY CONTRACT
**Severity: CRITICAL | Files: `AgentScorer.sol`, `AgenticCommerceV2.sol`, `ProtocolCredits.sol`**

All three contracts hardcode `owner = msg.sender` in the constructor with no `transferOwnership()` function.

**Impact:** If deployer key is lost or compromised, contracts are permanently locked. No admin recovery, no governance upgrade path.

**Fix:** Implement two-step ownership transfer (propose + accept pattern).

---

### C5: UNAUTHENTICATED WORKER REGISTRATION
**Severity: CRITICAL | File: `agent_market/api/server.py:582-675`**

`POST /register-worker` only checks if the health endpoint is reachable. No cryptographic identity verification:
- No wallet signature required
- No rate limiting per IP on registration
- No proof that registrant owns the endpoint

**Attack:** Register 1000 fake workers pointing to attacker-controlled server. All job routing gets intercepted.

**Fix:** Require EIP-712 signed message proving wallet ownership. Add per-IP rate limiting.

---

### C6: RACE CONDITION IN ON-CHAIN NONCE HANDLING
**Severity: CRITICAL | Files: `agent_market/chain.py`, `commerce.py`, `registry.py`, `token.py`, `erc8004.py`**

Every transaction calls `get_transaction_count()` without global locking:
```python
"nonce": self.w3.eth.get_transaction_count(self.account.address),
```

Under concurrent requests, two threads get the same nonce, one transaction fails silently.

The `_onchain_lock` in `server.py` only protects the background thread, not FastAPI request handlers.

**Fix:** Use a global RLock spanning nonce-get through tx-send across ALL on-chain callers.

---

### C7: MISSING PAYMENT AMOUNT VALIDATION (x402)
**Severity: CRITICAL | File: `agent_market/x402.py:178-199`**

x402 payment verification checks that a Transfer event occurred but **never validates the amount**:
```python
if to_addr.lower() == expected_recipient:
    return True, f"AVNC token payment verified"  # No amount check!
```

**Attack:** Send 0.000001 AVNC instead of required amount. Payment passes.

**Fix:** Decode `log_entry.data` to extract transfer amount and compare against minimum price.

---

## SECTION 2: HIGH SEVERITY FINDINGS

### H1: PERMISSIVE CORS (allow_origins=["*"])
**File: `agent_market/api/server.py:44-51`**

Allows any website to make authenticated API calls. Enables credential theft via malicious sites.

**Fix:** Whitelist specific origins only.

---

### H2: WORKER FAILURE RETURNS passed=True
**File: `agent_market/worker/forward.py:69-78`**

When analysis crashes (OOM, timeout, any exception), the catch-all returns `passed=True` with empty issues. Dangerous code gets approved silently.

**Fix:** Set `passed=False` in all error paths.

---

### H3: SSRF VIA WORKER ENDPOINTS
**File: `agent_market/api/server.py:401-425`**

Worker endpoints from Supabase are used directly in HTTP requests without validation:
```python
req = urllib.request.Request(f"{worker['endpoint'].rstrip('/')}/verify", ...)
```

Could be `http://169.254.169.254/` (cloud metadata), `http://localhost:9000/` (internal services), or `file:///etc/passwd`.

**Fix:** Validate URL scheme (https only), block private/reserved IPs, block localhost.

---

### H4: NO RATE LIMITING ON /verify ENDPOINT
**File: `agent_market/api/server.py:251-519`**

Main verification endpoint has no per-IP or per-key rate limiting. Only registration has a basic check.

**Fix:** Add `slowapi` rate limiter or similar. 10 req/min per IP, 100 req/min per API key.

---

### H5: RACE CONDITION IN FILE-BASED LOGGING
**File: `agent_market/logger.py:17-50`**

Read-modify-write pattern without file locking. Concurrent requests lose log entries.

**Fix:** Use `fcntl.flock()` or switch to append-only JSONL format.

---

### H6: FAUCET UNBOUNDED MINTING (ProtocolCredits.sol)
**File: `contracts/ProtocolCredits.sol:36-45`**

Any address can mint 20 AVNC every 24 hours forever. 1000 Sybil accounts = 7.3M AVNC/year vs 1M initial supply.

**Fix:** Cap total faucet supply. Add maximum total supply. Decrease faucet amount over time.

---

### H7: FEE CHANGE AFFECTS IN-PROGRESS JOBS
**File: `contracts/AgenticCommerceV2.sol:168-172`**

Owner can change `validatorFeeBps` while jobs are in progress. A job funded at 15% fee could be completed at 50%.

**Fix:** Store fee at job creation time, not globally.

---

### H8: NO EXPIRATION FOR PENDING JOBS
**Files: `contracts/AgenticCommerceV2.sol`, `AgenticCommerce.sol`**

Jobs in `Submitted` state can remain pending forever. No timeout to refund clients if evaluator disappears.

**Fix:** Add timestamp-based expiration with client withdrawal after X days.

---

### H9: UNVALIDATED WORKER RESPONSE SCHEMAS
**File: `agent_market/api/server.py:420-424`**

Worker responses are parsed as JSON and trusted completely. No schema validation, no size limits.

**Fix:** Validate response structure. Limit response body to 10MB. Reject malformed data.

---

### H10: NO RESPONSE SIZE LIMITS
**File: `agent_market/api/server.py:420`**

`resp.read()` has no size limit. A malicious worker can stream unlimited data causing OOM.

**Fix:** `resp.read(10_000_000)` with size check.

---

### H11: MinerRegistry STRING COLLISION RISK
**File: `contracts/MinerRegistry.sol:25-41`**

Uses raw strings as mapping keys. Unicode normalization issues allow homograph attacks ("alice" vs "аlice" with Cyrillic).

**Fix:** Use `bytes32 keccak256(agentId)` for unique identification.

---

## SECTION 3: MEDIUM SEVERITY FINDINGS

### M1: DOCKER CONTAINERS RUN AS ROOT
**Files: `Dockerfile`, `Dockerfile.worker`**

No `USER` directive. Container compromise = root access.

**Fix:** Add `RUN useradd -m appuser` and `USER appuser`.

---

### M2: MISSING SECURITY HEADERS (Next.js)
**File: `web/next.config.ts`**

Empty config. No CSP, X-Frame-Options, X-Content-Type-Options, HSTS.

**Fix:** Add security headers in `next.config.ts` `headers()` function.

---

### M3: NO INPUT VALIDATION ON FRONTEND ROUTES
**Files: `web/app/agent/[agentId]/page.tsx`, all page components**

`agentId` from URL params used without validation. API responses rendered without sanitization.

**Fix:** Validate params with regex/Zod. Use error boundaries.

---

### M4: BARE EXCEPT CLAUSES EVERYWHERE
**Files: `keys.py:55-57`, `erc8004.py:127`, `chain.py:60`, `commerce.py:62`, `registry.py:58`, `token.py:64`**

Broad `except Exception` handlers silently disable on-chain features. Corrupted private key = silent failure.

**Fix:** Catch specific exceptions. Log CRITICAL for configuration errors. Crash on startup if required config is invalid.

---

### M5: SQL/URL INJECTION IN SUPABASE QUERIES
**File: `agent_market/api/server.py:1549-1550`**

User-supplied `agent_id` interpolated directly into Supabase REST query strings without escaping.

**Fix:** Use `urllib.parse.quote()` on all user-supplied values.

---

### M6: DIVISION-BY-ZERO EDGE CASES IN SCORER
**File: `agent_market/manager/scorer.py:129-137`**

Uses `max(1, ...)` guard but masks incorrect false-positive calculation when `found_issues` is empty.

**Fix:** Handle empty-issues case explicitly.

---

### M7: NO CODE SIZE LIMITS ON ANALYSIS INPUT
**File: `agent_market/worker/analyzer.py:281`**

`analyze_code()` accepts arbitrarily large code strings. 100MB input = server hang.

**Fix:** Add `MAX_CODE_LENGTH = 1_000_000` check.

---

### M8: MIXED TIMESTAMP FORMATS
**Files: `agent_market/logger.py:42`, `agent_market/api/server.py:976`**

Some use `strftime` with Z suffix, others use `isoformat()` with `+00:00`. Fragile parsing.

**Fix:** Standardize on ISO 8601 with Z suffix throughout.

---

### M9: ERC-20 APPROVE RACE CONDITION (ProtocolCredits.sol)
**File: `contracts/ProtocolCredits.sol:69-72`**

Standard `approve()` without `increaseAllowance`/`decreaseAllowance`. Known front-running vulnerability.

**Fix:** Add `increaseAllowance()` and `decreaseAllowance()` per OpenZeppelin pattern.

---

### M10: TOKEN TRANSFER TO address(0) ALLOWED
**File: `contracts/ProtocolCredits.sol:61-82`**

No check prevents transfers to zero address, silently burning tokens without a Burn event.

**Fix:** Block address(0) or implement explicit `burn()`.

---

### M11: CI/CD COMMAND INJECTION
**File: `.github/workflows/verify-code.yml:50`**

Filename interpolated into Python command without quoting:
```bash
CODE_JSON=$(python3 -c "import json; print(json.dumps(open('$FILE').read()))")
```

**Fix:** Use `sys.stdin.read()` with pipe instead.

---

### M12: HARDCODED API ENDPOINT IN FRONTEND
**Files: All `web/app/*/page.tsx`**

```typescript
const API_BASE = "https://agent-verification-network-production.up.railway.app";
```

Can't switch environments without code change.

**Fix:** Use `process.env.NEXT_PUBLIC_API_BASE`.

---

### M13: MinerRegistry getActiveMinerCount() IS O(n)
**File: `contracts/MinerRegistry.sol:75-79`**

Loops through all miners. At scale, hits block gas limits.

**Fix:** Cache active count in storage variable.

---

### M14: dangerouslySetInnerHTML IN LAYOUT
**File: `web/app/layout.tsx:31-38`**

Used for theme initialization script. Currently safe but fragile pattern.

**Fix:** Move to separate inline script. Never use with dynamic data.

---

## SECTION 4: LOW SEVERITY / CODE QUALITY

### L1: BACKWARD COMPATIBILITY ALIASES
**Files: `manager/honeypot.py:335`, `manager/scorer.py:289`**

`HoneypotGenerator = SpotCheckGenerator` and `MinerScorer = WorkerScorer` aliases still exist. Remove once rename is complete.

### L2: DEAD CONSENSUS SCORING CODE
**File: `manager/scorer.py`, `manager/forward.py`**

Consensus scoring exists in scorer but `forward.py` never passes `all_responses`. Documented as known dead code.

### L3: MAGIC NUMBERS THROUGHOUT
**Files: `manager/forward.py:43`, `api/server.py:1351`, `api/server.py:960`, `manager/scorer.py:230`**

Probation threshold (20), rate limit hours (3600), claim expiry (600), line bucket size (3) are all magic numbers.

### L4: MISSING GAS ESTIMATION HANDLING
**Files: `chain.py`, `commerce.py`, `registry.py`, `token.py`, `erc8004.py`**

No explicit gas limits set. Relies on auto-estimation which can fail for complex calls.

### L5: NO JITTER IN POLLING LOOP
**File: `agent_market/api/server.py:318-322`**

Fixed 1-second polling intervals. Thundering herd under load.

### L6: UNPINNED PYTHON DEPENDENCIES
**File: `pyproject.toml`**

Versions like `"fastapi"`, `"uvicorn"` have no pins. Transitive vulnerability risk.

### L7: MISSING BASE64 VALIDATION ON IMAGE INPUT
**File: `agent_market/protocol.py:27-32`**

Validates image size but not base64 encoding validity.

### L8: NO TRANSACTION DETAIL LOGGING
**File: `agent_market/chain.py:98`**

Logs tx hash but not agent_id, score, gas used, or block number.

### L9: INSUFFICIENT TEST COVERAGE
**Files: `test/test_verification.py`, `test/test_image_verification.py`, `test/test_x402.py`**

Only 3 test files. No tests for: registration, scoring, spot checks, consensus, commerce, payment flows, error paths, concurrent access.

### L10: MISSING ENV CONFIGURATION VISIBILITY
No `/config` endpoint to show what features are enabled/disabled at runtime.

### L11: DUPLICATE FORMAT DETECTION CALLS
**File: `agent_market/worker/image_analyzer.py:284-287`**

`detect_format(data)` called twice on the same data.

### L12: NO PAUSE MECHANISM ON TOKEN CONTRACT
**File: `contracts/ProtocolCredits.sol`**

No emergency pause if vulnerability is discovered post-deploy.

---

## SECTION 5: ARCHITECTURE ASSESSMENT

### Strengths
1. **Spot check mechanism is novel and sound** — genuine competitive advantage over competitors
2. **Three-role separation (Client/Worker/Manager)** is clean and well-defined
3. **Chain-agnostic core** — analyzer, honeypot, scorer have no chain imports (as intended)
4. **Multi-vertical support** — code, text, and image verification live
5. **Payment flexibility** — API keys, x402, on-chain escrow, faucet all implemented

### Weaknesses
1. **Consensus scoring is dead** — `forward.py` never passes `all_responses` to scorer. Major feature gap.
2. **Static spot checks can be memorized** — 12 bug + 2 clean templates are finite. Workers can fingerprint them. Dynamic LLM-generated spot checks are critical.
3. **Single-manager architecture** — one manager routes all jobs. No manager competition or redundancy.
4. **No dispute resolution** — if worker disagrees with rating, no appeal mechanism.
5. **File-based logging** — `agent_log.json` doesn't scale. Need structured logging to external service.
6. **No job queue** — synchronous polling loop. Doesn't scale past ~50 concurrent requests.

---

## SECTION 6: DEPLOYMENT CHECKLIST

### MUST DO (Before any mainnet use)
- [ ] Remove ALL hardcoded secrets from source (keys.py, erc8004.py, x402.py)
- [ ] Rotate Supabase JWT, Alchemy API key, all private keys in .env files
- [ ] Add nonReentrant guard to AgenticCommerceV2 complete()/reject()
- [ ] Implement signed worker registration (EIP-712)
- [ ] Add rate limiting to /verify and /register-worker endpoints
- [ ] Fix worker error handling (passed=False on failure)
- [ ] Add x402 payment amount validation
- [ ] Add SSRF protection on worker endpoint requests
- [ ] Add response size limits on worker responses
- [ ] Implement global nonce lock for on-chain transactions
- [ ] Add owner transfer to AgentScorer, AgenticCommerceV2, ProtocolCredits
- [ ] Cap faucet total supply in ProtocolCredits
- [ ] Restrict CORS to known origins

### SHOULD DO (Before production scale)
- [ ] Wire up consensus scoring in forward.py
- [ ] Implement dynamic LLM-generated spot checks
- [ ] Add job expiration to commerce contracts
- [ ] Store fee-at-creation in AgenticCommerceV2
- [ ] Add security headers to Next.js config
- [ ] Run Docker as non-root
- [ ] Pin all Python/JS dependencies
- [ ] Add comprehensive test suite (target >80% coverage)
- [ ] Switch from file logging to structured external logging
- [ ] Add /config endpoint for runtime feature visibility
- [ ] Implement circuit breakers for RPC calls

### NICE TO HAVE
- [ ] Add dispute resolution mechanism
- [ ] Implement manager competition/redundancy
- [ ] Add job queue (Redis/RabbitMQ) for async processing
- [ ] Add increaseAllowance/decreaseAllowance to AVNC token
- [ ] Add Pausable pattern to token contract
- [ ] Add pagination to MinerRegistry
- [ ] Move timestamp handling to single utility function

---

**END OF AUDIT REPORT**

