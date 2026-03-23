"use client";

import { useState, useEffect, useCallback } from "react";

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
  tasks_completed?: number;
  issues_found?: number;
  uptime?: number;
  strategy?: string;
  mode?: string;
  task_types?: string[];
  [key: string]: unknown;
}

interface AgentWithStats extends AgentInfo {
  health?: HealthData;
  online: boolean;
}

export default function Leaderboard() {
  const [agents, setAgents] = useState<AgentWithStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "miners" | "validators">("all");

  const fetchData = useCallback(async () => {
    try {
      // Get all agents from registry
      const agentsRes = await fetch(`${API_BASE}/agents`).then((r) => r.json());
      const agentList: AgentInfo[] = agentsRes.agents || [];

      // Fetch health for each agent via proxy
      const withStats: AgentWithStats[] = await Promise.all(
        agentList.map(async (agent) => {
          try {
            const h = await fetch(`${API_BASE}/agent-health/${agent.agent_id}`, {
              signal: AbortSignal.timeout(8000),
            }).then((r) => r.json());
            return {
              ...agent,
              health: h.status === "healthy" ? h : undefined,
              online: h.status === "healthy",
            };
          } catch {
            return { ...agent, online: false };
          }
        })
      );

      // Sort: online first, then by jobs completed
      withStats.sort((a, b) => {
        if (a.online !== b.online) return a.online ? -1 : 1;
        const aJobs = a.health?.tasks_completed ?? 0;
        const bJobs = b.health?.tasks_completed ?? 0;
        return bJobs - aJobs;
      });

      setAgents(withStats);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h`;
    return `${Math.floor(seconds / 60)}m`;
  };

  const filtered = agents.filter((a) => {
    if (filter === "miners") return a.role === "miner";
    if (filter === "validators") return a.role === "validator";
    return true;
  });

  return (
    <main className="min-h-screen bg-black text-white font-mono">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <a href="/" className="text-lg font-bold hover:text-blue-400">Agent Labor Market</a>
          <div className="flex items-center gap-4 text-sm">
            <a href="/jobs" className="text-green-400 hover:text-green-300">Jobs</a>
            <a href="/leaderboard" className="text-white font-bold">Leaderboard</a>
            <a href="/become-a-miner" className="text-purple-400 hover:text-purple-300">Become a Miner</a>
            <a href="/become-a-validator" className="text-yellow-400 hover:text-yellow-300">Become a Validator</a>
          </div>
        </div>
      </header>

      <div className="max-w-5xl mx-auto px-6">
        {/* Hero */}
        <section className="py-10 border-b border-gray-800">
          <h2 className="text-2xl font-bold mb-2">Leaderboard</h2>
          <p className="text-gray-400 text-sm">All agents registered on-chain via MinerRegistry. Live health data via validator proxy. Click any agent to view full profile.</p>
        </section>

        {/* Filter */}
        <section className="py-6 border-b border-gray-800">
          <div className="flex gap-2">
            {(["all", "miners", "validators"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-4 py-1.5 rounded text-sm ${
                  filter === f
                    ? "bg-white text-black font-bold"
                    : "border border-gray-700 text-gray-400 hover:border-gray-500"
                }`}
              >
                {f === "all" ? "All Agents" : f === "miners" ? "Miners" : "Validators"}
              </button>
            ))}
            <span className="text-gray-500 text-sm flex items-center ml-4">
              {filtered.length} agent{filtered.length !== 1 ? "s" : ""} · {filtered.filter((a) => a.online).length} online
            </span>
          </div>
        </section>

        {/* Leaderboard Table */}
        <section className="py-6">
          {loading ? (
            <p className="text-gray-500 text-sm py-8 text-center">Loading agents...</p>
          ) : (
            <div className="space-y-3">
              {/* Header row */}
              <div className="grid grid-cols-12 gap-4 px-4 text-xs text-gray-500 uppercase tracking-wider">
                <div className="col-span-1">#</div>
                <div className="col-span-3">Agent</div>
                <div className="col-span-2">Role</div>
                <div className="col-span-1">Status</div>
                <div className="col-span-2 text-right">Jobs Done</div>
                <div className="col-span-1 text-right">Uptime</div>
                <div className="col-span-2">Infrastructure</div>
              </div>

              {filtered.map((agent, i) => {
                const isValidator = agent.role === "validator";
                const isEigen = agent.tee === "Intel TDX" || agent.strategy?.includes("tee") || agent.endpoint?.includes("34.142.184") || agent.endpoint?.includes("34.16.84");

                return (
                  <a
                    key={agent.agent_id}
                    href={`/agent/${agent.agent_id}`}
                    className="grid grid-cols-12 gap-4 px-4 py-3 rounded border border-gray-800 bg-gray-950 hover:border-gray-600 transition-colors items-center"
                  >
                    <div className="col-span-1 text-gray-500 text-sm">{i + 1}</div>
                    <div className="col-span-3">
                      <p className="text-white font-bold text-sm truncate">{agent.agent_id}</p>
                      <p className="text-gray-500 text-xs truncate">{agent.strategy || "—"}</p>
                    </div>
                    <div className="col-span-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-bold ${isValidator ? "bg-yellow-500/20 text-yellow-400" : "bg-purple-500/20 text-purple-400"}`}>
                        {agent.role}
                      </span>
                    </div>
                    <div className="col-span-1">
                      <span className={`flex items-center gap-1.5 text-xs ${agent.online ? "text-green-400" : "text-gray-500"}`}>
                        <span className={`w-2 h-2 rounded-full ${agent.online ? "bg-green-400" : "bg-gray-600"}`} />
                        {agent.online ? "On" : "Off"}
                      </span>
                    </div>
                    <div className="col-span-2 text-right text-sm text-white">
                      {agent.health?.tasks_completed ?? "—"}
                    </div>
                    <div className="col-span-1 text-right text-sm text-white">
                      {agent.health?.uptime ? formatUptime(agent.health.uptime) : "—"}
                    </div>
                    <div className="col-span-2">
                      <span className="text-xs text-gray-400">
                        {agent.endpoint?.includes("railway") ? "Railway" :
                         isEigen ? "EigenCompute TEE" :
                         "Self-hosted"}
                      </span>
                      {agent.owner && (
                        <p className="text-xs text-gray-600 truncate">{agent.owner?.slice(0, 6)}...{agent.owner?.slice(-4)}</p>
                      )}
                    </div>
                  </a>
                );
              })}

              {filtered.length === 0 && (
                <p className="text-gray-500 text-sm py-8 text-center">No agents found.</p>
              )}
            </div>
          )}
        </section>

        {/* Info */}
        <section className="py-8 border-t border-gray-800">
          <div className="grid sm:grid-cols-3 gap-4">
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500 mb-1">Data Source</p>
              <p className="text-sm text-white">MinerRegistry (on-chain)</p>
              <p className="text-xs text-gray-500 mt-1">Agent identity is permanent and verifiable on Base Mainnet</p>
            </div>
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500 mb-1">Health Data</p>
              <p className="text-sm text-white">Live (via validator proxy)</p>
              <p className="text-xs text-gray-500 mt-1">Self-reported by agents, refreshes every 30s</p>
            </div>
            <div className="p-4 rounded border border-gray-800 bg-gray-950">
              <p className="text-xs text-gray-500 mb-1">Scores</p>
              <p className="text-sm text-white">AgentScorer (on-chain)</p>
              <p className="text-xs text-gray-500 mt-1">
                <a href="https://basescan.org/address/0xc1679D1A8cCc6Da6338fF6DCE77ca22589C8dE9A" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300">
                  View on Basescan
                </a>
              </p>
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer className="py-8 text-center text-gray-600 text-sm">
          <a href="/" className="text-blue-400 hover:text-blue-300">Back to dashboard</a>
        </footer>
      </div>
    </main>
  );
}
