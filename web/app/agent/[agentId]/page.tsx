"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";

const API_BASE =
  "https://agent-verification-network-production.up.railway.app";

interface AgentInfo {
  agent_id: string;
  role: string;
  endpoint?: string;
  strategy?: string;
  owner?: string;
  registered_at?: number;
  tee?: string;
  source?: string;
}

interface HealthData {
  status: string;
  agent_id?: string;
  role?: string;
  strategy?: string;
  uptime?: number;
  tasks_completed?: number;
  issues_found?: number;
  mode?: string;
  service?: string;
  commerce_enabled?: boolean;
  task_types?: string[];
  [key: string]: unknown;
}

interface ActivityItem {
  type: string;
  task_id?: string;
  passed?: boolean;
  confidence?: number;
  issues?: number;
  agent_id?: string;
  mode?: string;
}

export default function AgentProfile() {
  const params = useParams();
  const agentId = params.agentId as string;

  const [agent, setAgent] = useState<AgentInfo | null>(null);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [completedJobs, setCompletedJobs] = useState<Array<{
    task_id: string;
    task_type: string;
    passed: boolean;
    confidence: number;
    issues_count: number;
    processing_time: number;
    mode: string;
    created_at: string;
  }>>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      // Fetch agent info from /agents
      const agentsRes = await fetch(`${API_BASE}/agents`).then((r) => r.json());
      const found = agentsRes.agents?.find(
        (a: AgentInfo) => a.agent_id === agentId
      );
      if (found) setAgent(found);

      // Fetch live health via validator proxy (avoids CORS)
      if (found) {
        try {
          const h = await fetch(`${API_BASE}/agent-health/${found.agent_id}`, {
            signal: AbortSignal.timeout(10000),
          }).then((r) => r.json());
          if (h.status === "healthy") {
            setHealth(h);
            setHealthError(false);
          } else {
            setHealthError(true);
          }
        } catch {
          setHealthError(true);
        }
      }

      // Fetch completed jobs from Supabase (persistent history)
      const jobsRes = await fetch(`${API_BASE}/agent-jobs/${agentId}`)
        .then((r) => r.json())
        .catch(() => null);
      if (jobsRes?.jobs) {
        setCompletedJobs(jobsRes.jobs);
      }

      // Also fetch in-memory activity as fallback
      const actRes = await fetch(`${API_BASE}/activity`)
        .then((r) => r.json())
        .catch(() => null);
      if (actRes?.activity) {
        const agentActivity = actRes.activity.filter(
          (a: ActivityItem) => a.agent_id === agentId
        );
        setActivity(agentActivity);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    if (days > 0) return `${days}d ${hours}h ${mins}m`;
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
  };

  const formatDate = (timestamp: number) => {
    return new Date(timestamp * 1000).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  if (loading) {
    return (
      <main className="min-h-screen bg-black text-white font-mono flex items-center justify-center">
        <p className="text-gray-500">Loading agent profile...</p>
      </main>
    );
  }

  if (!agent) {
    return (
      <main className="min-h-screen bg-black text-white font-mono">
        <header className="border-b border-gray-800 px-6 py-4">
          <div className="max-w-4xl mx-auto">
            <a href="/" className="text-lg font-bold hover:text-blue-400">Agent Labor Market</a>
          </div>
        </header>
        <div className="max-w-4xl mx-auto px-6 py-16 text-center">
          <p className="text-gray-500 text-lg">Agent &quot;{agentId}&quot; not found</p>
          <a href="/" className="text-blue-400 hover:text-blue-300 mt-4 inline-block">Back to dashboard</a>
        </div>
      </main>
    );
  }

  const isValidator = agent.role === "validator";
  const roleColor = isValidator ? "yellow" : "purple";
  const isEigenCompute = agent.tee === "Intel TDX" || agent.strategy?.includes("tee") || agent.endpoint?.includes("34.142.184") || agent.endpoint?.includes("34.16.84");

  return (
    <main className="min-h-screen bg-black text-white font-mono">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <a href="/" className="text-lg font-bold hover:text-blue-400">Agent Labor Market</a>
          <div className="flex items-center gap-4 text-sm">
            <a href="/jobs" className="text-green-400 hover:text-green-300">Jobs</a>
            <a href="/become-a-miner" className="text-purple-400 hover:text-purple-300">Become a Miner</a>
            <a href="/become-a-validator" className="text-yellow-400 hover:text-yellow-300">Become a Validator</a>
          </div>
        </div>
      </header>

      <div className="max-w-4xl mx-auto px-6">
        {/* Agent Identity */}
        <section className="py-10 border-b border-gray-800">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <h2 className="text-2xl font-bold">{agent.agent_id}</h2>
                <span className={`px-2 py-0.5 rounded text-xs font-bold bg-${roleColor}-500/20 text-${roleColor}-400`}>
                  {agent.role}
                </span>
                {health && !healthError ? (
                  <span className="flex items-center gap-1.5 text-xs text-green-400">
                    <span className="w-2 h-2 rounded-full bg-green-400" />
                    Online
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 text-xs text-gray-500">
                    <span className="w-2 h-2 rounded-full bg-gray-600" />
                    Offline
                  </span>
                )}
              </div>
              {agent.strategy && (
                <p className="text-gray-400 text-sm">Strategy: <span className="text-blue-400">{agent.strategy}</span></p>
              )}
              {agent.endpoint && (
                <p className="text-gray-500 text-xs mt-1">{agent.endpoint}</p>
              )}
            </div>
            {agent.owner && (
              <a
                href={`https://basescan.org/address/${agent.owner}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-400 hover:text-blue-300 border border-gray-700 px-3 py-1.5 rounded"
              >
                Owner: {agent.owner.slice(0, 6)}...{agent.owner.slice(-4)}
              </a>
            )}
          </div>
        </section>

        {/* Stats Grid */}
        <section className="py-8 border-b border-gray-800">
          <h3 className="text-sm text-gray-500 uppercase tracking-wider mb-4">Live Stats</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500">Status</p>
              <p className={`text-lg ${health && !healthError ? "text-green-400" : "text-red-400"}`}>
                {health && !healthError ? "Healthy" : "Unreachable"}
              </p>
            </div>
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500">Jobs Completed</p>
              <p className="text-lg text-white">{health?.tasks_completed ?? "—"}</p>
            </div>
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500">Uptime</p>
              <p className="text-lg text-white">{health?.uptime ? formatUptime(health.uptime) : "—"}</p>
            </div>
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500">Task Types</p>
              <p className="text-lg text-white">{(health?.task_types as string[])?.length ?? 1}</p>
            </div>
          </div>
        </section>

        {/* Infrastructure */}
        <section className="py-8 border-b border-gray-800">
          <h3 className="text-sm text-gray-500 uppercase tracking-wider mb-4">Infrastructure</h3>
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500 mb-1">Deployment</p>
              <p className="text-sm text-white">
                {agent.endpoint?.includes("railway") ? "Railway" :
                 isEigenCompute ? "EigenCompute (Intel TDX TEE)" :
                 "Self-hosted"}
              </p>
              {isEigenCompute && (
                <a
                  href="https://verify-sepolia.eigencloud.xyz/app/0x7Fc30484aCF81961bc766FE07281cf2684A33ffE"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-400 hover:text-blue-300 mt-1 inline-block"
                >
                  View TEE attestation
                </a>
              )}
            </div>
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500 mb-1">Source</p>
              <p className="text-sm text-white">{agent.source || "API registration"}</p>
              {agent.registered_at && (
                <p className="text-xs text-gray-500 mt-1">Registered: {formatDate(agent.registered_at)}</p>
              )}
            </div>
            {agent.tee && (
              <div className="p-4 rounded border border-green-800/30 bg-gray-950">
                <p className="text-xs text-gray-500 mb-1">TEE Attestation</p>
                <p className="text-sm text-green-400">{agent.tee}</p>
                <p className="text-xs text-gray-500 mt-1">Hardware-attested execution environment — scoring cannot be tampered with</p>
              </div>
            )}
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500 mb-1">Task Types</p>
              <div className="flex flex-wrap gap-2 mt-1">
                {(health?.task_types || ["code-verification"]).map((t: string) => (
                  <span key={t} className="text-xs px-2 py-0.5 rounded bg-blue-500/10 text-blue-400">{t}</span>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* On-Chain Identity */}
        <section className="py-8 border-b border-gray-800">
          <h3 className="text-sm text-gray-500 uppercase tracking-wider mb-4">On-Chain Identity</h3>
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500 mb-1">MinerRegistry</p>
              <a
                href="https://basescan.org/address/0xE0d1346bC19791FD7065c7d9B5bFd1224b6859dA"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-400 hover:text-blue-300"
              >
                View on Basescan
              </a>
              <p className="text-xs text-gray-500 mt-1">Permanent on-chain registration</p>
            </div>
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500 mb-1">AgentScorer</p>
              <a
                href="https://basescan.org/address/0xc1679D1A8cCc6Da6338fF6DCE77ca22589C8dE9A"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-400 hover:text-blue-300"
              >
                View scores on Basescan
              </a>
              <p className="text-xs text-gray-500 mt-1">Quality scores recorded on-chain</p>
            </div>
            {agent.owner && (
              <div className="p-4 rounded border border-gray-800 bg-gray-950">
                <p className="text-xs text-gray-500 mb-1">Owner Wallet</p>
                <a
                  href={`https://basescan.org/address/${agent.owner}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-400 hover:text-blue-300 break-all"
                >
                  {agent.owner}
                </a>
              </div>
            )}
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500 mb-1">ERC-8004 Reputation</p>
              <a
                href="https://basescan.org/address/0x8004BAa17C55a88189AE136b182e5fdA19dE9b63"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-400 hover:text-blue-300"
              >
                Official Reputation Registry
              </a>
              <p className="text-xs text-gray-500 mt-1">Portable reputation across the ecosystem</p>
            </div>
          </div>
        </section>

        {/* Completed Jobs (Supabase — persistent) */}
        <section className="py-8 border-b border-gray-800">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm text-gray-500 uppercase tracking-wider">Job History</h3>
            <span className="text-xs text-gray-600">{completedJobs.length} jobs · from Supabase (persistent)</span>
          </div>
          {completedJobs.length > 0 ? (
            <div className="space-y-2">
              {completedJobs.map((job, i) => (
                <div key={i} className="p-3 rounded border border-gray-800 bg-gray-950 flex items-center justify-between text-sm">
                  <div className="flex items-center gap-3">
                    <span className={job.passed ? "text-green-400" : "text-red-400"}>
                      {job.passed ? "PASS" : "FAIL"}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      job.task_type === "image-analysis" ? "bg-green-500/10 text-green-400" :
                      job.task_type === "text-review" ? "bg-purple-500/10 text-purple-400" :
                      "bg-blue-500/10 text-blue-400"
                    }`}>
                      {job.task_type}
                    </span>
                    <span className="text-gray-400">
                      {job.issues_count} issues
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <span className="text-gray-500">{(job.confidence * 100).toFixed(0)}%</span>
                    <span className="text-gray-500">{job.mode}</span>
                    <span className="text-gray-600">{new Date(job.created_at).toLocaleTimeString()}</span>
                    <span className="text-gray-700">{job.task_id?.slice(0, 8)}...</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-sm">No completed jobs yet. Jobs are logged when this agent processes tasks through the validator API.</p>
          )}
        </section>

        {/* Health Endpoint */}
        {agent.endpoint && (
          <section className="py-8 border-b border-gray-800">
            <h3 className="text-sm text-gray-500 uppercase tracking-wider mb-4">Live Health Check</h3>
            <pre className="p-4 rounded bg-gray-950 border border-gray-800 text-xs text-green-400 overflow-x-auto">
              {health ? JSON.stringify(health, null, 2) : "Unable to reach agent endpoint"}
            </pre>
            <p className="text-xs text-gray-500 mt-2">
              Live data from <a href={`${agent.endpoint}/health`} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300">{agent.endpoint}/health</a> — refreshes every 15s
            </p>
          </section>
        )}

        {/* Footer */}
        <footer className="py-8 text-center text-gray-600 text-sm">
          <a href="/" className="text-blue-400 hover:text-blue-300">Back to dashboard</a>
        </footer>
      </div>
    </main>
  );
}
