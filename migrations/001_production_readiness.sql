-- Migration: Production Readiness
-- Date: 2026-04-01
-- Description: Add tables for persistent worker scores and event indexer state.
--              Add columns to marketplace_jobs for on-chain event sync.

-- Worker scores: persists EMA scores across server restarts
CREATE TABLE IF NOT EXISTS worker_scores (
  id BIGSERIAL PRIMARY KEY,
  agent_id TEXT NOT NULL UNIQUE,
  running_score FLOAT NOT NULL DEFAULT 0.0,
  jobs_completed INT NOT NULL DEFAULT 0,
  last_round INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Event indexer state: tracks last processed block for on-chain event sync
CREATE TABLE IF NOT EXISTS indexer_state (
  id INT PRIMARY KEY DEFAULT 1,
  last_block BIGINT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add on-chain sync columns to marketplace_jobs
ALTER TABLE marketplace_jobs ADD COLUMN IF NOT EXISTS on_chain_status TEXT;
ALTER TABLE marketplace_jobs ADD COLUMN IF NOT EXISTS worker_address TEXT;
ALTER TABLE marketplace_jobs ADD COLUMN IF NOT EXISTS funded_amount BIGINT;
ALTER TABLE marketplace_jobs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE marketplace_jobs ADD COLUMN IF NOT EXISTS payout BIGINT;
ALTER TABLE marketplace_jobs ADD COLUMN IF NOT EXISTS fee BIGINT;

-- Add role column to registered_workers if missing
ALTER TABLE registered_workers ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'worker';

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_worker_scores_agent_id ON worker_scores(agent_id);
CREATE INDEX IF NOT EXISTS idx_completed_jobs_agent_id ON completed_jobs(agent_id);
CREATE INDEX IF NOT EXISTS idx_marketplace_jobs_on_chain_id ON marketplace_jobs(on_chain_job_id);
