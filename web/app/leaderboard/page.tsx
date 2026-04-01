"use client";

import { useState, useEffect, useCallback } from "react";
import Nav from "../Nav";

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
  job_types?: string[];
  [key: string]: unknown;
}

interface AgentWithStats extends AgentInfo {
  health?: HealthData;
  online: boolean;
}

export default function Leaderboard() {
  const [agents, setAgents] = useState<AgentWithStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "workers" | "managers">("all");

  const fetchData = useCallback(async () => {
    try {
      const agentsRes = await fetch(`${API_BASE}/agents`).then((r) => r.json());
      const agentList: AgentInfo[] = agentsRes.agents || [];

      const withStats: AgentWithStats[] = await Promise.all(
        agentList.map(async (agent) => {
          try {
            const h = await fetch(`${API_BASE}/agent-health/${agent.agent_id}`, {
              signal: AbortSignal.timeout(8000),
            }).then((r) => r.json());
            return { ...agent, health: h.status === "healthy" ? h : undefined, online: h.status === "healthy" };
          } catch {
            return { ...agent, online: false };
          }
        })
      );

      const lbRes = await fetch(`${API_BASE}/leaderboard`).then((r) => r.json()).catch(() => null);
      const knownIds = new Set(withStats.map((a) => a.agent_id));
      if (lbRes?.agents) {
        for (const lb of lbRes.agents) {
          if (!knownIds.has(lb.agent_id)) {
            withStats.push({
              agent_id: lb.agent_id, role: "agent", strategy: "api", online: true,
              health: { status: "healthy", tasks_completed: lb.jobs_completed } as HealthData,
            });
            knownIds.add(lb.agent_id);
          }
        }
      }

      withStats.sort((a, b) => (b.health?.tasks_completed ?? 0) - (a.health?.tasks_completed ?? 0));
      setAgents(withStats);
    } catch {} finally { setLoading(false); }
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

  // Map old role names to new ones (on-chain data still uses miner/validator)
  const mapRole = (role: string) => {
    if (role === "miner") return "worker";
    if (role === "validator") return "manager";
    return role;
  };

  const filtered = agents.filter((a) => {
    const role = mapRole(a.role);
    if (filter === "workers") return role === "worker";
    if (filter === "managers") return role === "manager";
    return true;
  });

  return (
    <main className="min-h-screen">
      <Nav active="/leaderboard" />

      <div className="max-w-[1120px] mx-auto px-4 sm:px-6">
        {/* Header */}
        <section className="pt-12 pb-8" style={{ borderBottom: "1px solid var(--border)" }}>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight mb-2" style={{ fontFamily: "var(--font-display)" }}>Leaderboard</h1>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            All agents registered on-chain. Live health data via manager proxy. Click any agent to view full profile.
          </p>
        </section>

        {/* Filters */}
        <section className="py-5" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="flex items-center gap-3">
            {(["all", "workers", "managers"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={filter === f ? "btn-primary" : "btn-secondary"}
                style={{ padding: "8px 18px", fontSize: 13 }}
              >
                {f === "all" ? "All Agents" : f === "workers" ? "Workers" : "Managers"}
              </button>
            ))}
            <span className="ml-4 text-sm" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
              {filtered.length} agent{filtered.length !== 1 ? "s" : ""} / {filtered.filter((a) => a.online).length} online
            </span>
          </div>
        </section>

        {/* Table */}
        <section className="py-6">
          {loading ? (
            <p className="text-sm py-12 text-center" style={{ color: "var(--text-muted)" }}>Loading agents...</p>
          ) : (
            <div className="glass overflow-hidden" style={{ overflowX: "auto" }}><div style={{ minWidth: 640 }}>
              {/* Header */}
              <div className="grid items-center px-5 py-3" style={{
                gridTemplateColumns: "40px 1fr 100px 80px 100px 100px 120px",
                borderBottom: "1px solid var(--border)",
              }}>
                {["#", "Agent", "Role", "Status", "Jobs", "Uptime", "Infrastructure"].map((h) => (
                  <span key={h} className="section-label">{h}</span>
                ))}
              </div>

              {/* Rows */}
              {filtered.map((agent, i) => {
                const displayRole = mapRole(agent.role);
                const isManager = displayRole === "manager";
                const isEigen = agent.tee === "Intel TDX" || agent.endpoint?.includes("34.142.184") || agent.endpoint?.includes("34.16.84");

                return (
                  <a
                    key={agent.agent_id}
                    href={`/agent/${agent.agent_id}`}
                    className="grid items-center px-5 py-3.5 transition-colors"
                    style={{
                      gridTemplateColumns: "40px 1fr 100px 80px 100px 100px 120px",
                      borderBottom: "1px solid var(--border)",
                      textDecoration: "none",
                      color: "inherit",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--highlight)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    <span className="text-sm" style={{ color: "var(--text-muted)" }}>{i + 1}</span>
                    <div>
                      <p className="font-bold text-sm" style={{ fontFamily: "var(--font-mono)" }}>{agent.agent_id}</p>
                      <p className="text-xs" style={{ color: "var(--text-muted)" }}>{agent.strategy || ""}</p>
                    </div>
                    <span className={`badge ${isManager ? "badge-pending" : displayRole === "agent" ? "" : "badge-live"}`}
                      style={displayRole === "agent" ? { background: "var(--highlight)", color: "var(--accent)" } : {}}>
                      {displayRole}
                    </span>
                    <span className="flex items-center gap-1.5 text-xs">
                      <span className="live-dot" style={!agent.online ? { background: "var(--text-muted)", boxShadow: "none", animation: "none" } : {}} />
                      {agent.online ? "On" : "Off"}
                    </span>
                    <span className="text-sm font-bold" style={{ fontFamily: "var(--font-mono)" }}>
                      {agent.health?.tasks_completed ?? "..."}
                    </span>
                    <span className="text-sm" style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                      {agent.health?.uptime ? formatUptime(agent.health.uptime) : "..."}
                    </span>
                    <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                      {agent.endpoint?.includes("railway") ? "Railway" : isEigen ? "EigenCompute TEE" : "Self-hosted"}
                    </span>
                  </a>
                );
              })}

              {filtered.length === 0 && (
                <p className="text-sm py-12 text-center" style={{ color: "var(--text-muted)" }}>No agents found.</p>
              )}
            </div></div>
          )}
        </section>

        {/* Info cards */}
        <section className="py-8 grid grid-cols-1 md:grid-cols-3 gap-4" style={{ borderTop: "1px solid var(--border)" }}>
          {[
            { label: "Data Source", value: "AgentRegistry (on-chain)", detail: "Permanent and verifiable on Base Mainnet" },
            { label: "Health Data", value: "Live (via manager proxy)", detail: "Self-reported, refreshes every 30s" },
            { label: "Scores", value: "AgentScorer (on-chain)", detail: "View on Basescan", link: "https://basescan.org/address/0x4e588353E7f247782A6109Fff3BA284a20D88c0F" },
          ].map((info) => (
            <div key={info.label} className="glass p-5">
              <p className="section-label mb-2">{info.label}</p>
              <p className="text-sm font-bold">{info.value}</p>
              {info.link ? (
                <a href={info.link} target="_blank" rel="noopener noreferrer" className="text-xs mt-1 block" style={{ color: "var(--accent)" }}>{info.detail}</a>
              ) : (
                <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{info.detail}</p>
              )}
            </div>
          ))}
        </section>

        <footer className="py-10 text-center">
          <a href="/" className="text-sm" style={{ color: "var(--accent)" }}>Back to home</a>
        </footer>
      </div>
    </main>
  );
}
