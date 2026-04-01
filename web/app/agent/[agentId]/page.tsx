"use client";

import { useState, useEffect, useCallback } from "react";
import Nav from "../../Nav";
import { useParams } from "next/navigation";

const API_BASE = "https://agent-verification-network-production.up.railway.app";

interface AgentInfo { agent_id: string; role: string; endpoint?: string; strategy?: string; owner?: string; registered_at?: number; tee?: string; source?: string; }
interface HealthData { status: string; agent_id?: string; role?: string; strategy?: string; uptime?: number; jobs_completed?: number; issues_found?: number; mode?: string; service?: string; commerce_enabled?: boolean; job_types?: string[]; [key: string]: unknown; }
interface CompletedJob { job_id: string; job_type: string; passed: boolean; confidence: number; issues_count: number; processing_time: number; mode: string; created_at: string; }

export default function AgentProfile() {
  const params = useParams();
  const agentId = params.agentId as string;

  const [agent, setAgent] = useState<AgentInfo | null>(null);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [completedJobs, setCompletedJobs] = useState<CompletedJob[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const agentsRes = await fetch(`${API_BASE}/agents`).then((r) => r.json());
      let found = agentsRes.agents?.find((a: AgentInfo) => a.agent_id === agentId);
      if (!found) {
        const jobsRes = await fetch(`${API_BASE}/agent-jobs/${agentId}`).then((r) => r.json()).catch(() => null);
        if (jobsRes?.jobs?.length > 0) found = { agent_id: agentId, role: "agent", strategy: "api", source: "API (Supabase)" };
      }
      if (found) setAgent(found);

      if (found && found.role !== "agent") {
        try {
          const h = await fetch(`${API_BASE}/agent-health/${found.agent_id}`, { signal: AbortSignal.timeout(10000) }).then((r) => r.json());
          if (h.status === "healthy") { setHealth(h); setHealthError(false); } else { setHealthError(true); }
        } catch { setHealthError(true); }
      }

      const jobsRes = await fetch(`${API_BASE}/agent-jobs/${agentId}`).then((r) => r.json()).catch(() => null);
      if (jobsRes?.jobs) setCompletedJobs(jobsRes.jobs);
    } catch {} finally { setLoading(false); }
  }, [agentId]);

  useEffect(() => { fetchData(); const i = setInterval(fetchData, 15000); return () => clearInterval(i); }, [fetchData]);

  const formatUptime = (s: number) => { const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60); return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`; };

  if (loading) return (
    <main className="min-h-screen flex items-center justify-center">
      <p className="text-sm" style={{ color: "var(--text-muted)" }}>Loading agent profile...</p>
    </main>
  );

  if (!agent) return (
    <main className="min-h-screen">
      <div className="max-w-[1120px] mx-auto px-6 pt-4">
        <nav className="glass flex items-center justify-between px-6 py-3.5" style={{ borderRadius: 14 }}>
          <a href="/" className="text-lg font-bold tracking-tight" style={{ fontFamily: "var(--font-display)" }}>Agent Labor Market</a>
        </nav>
      </div>
      <div className="max-w-[1120px] mx-auto px-6 py-16 text-center">
        <p className="text-lg" style={{ color: "var(--text-muted)" }}>Agent &quot;{agentId}&quot; not found</p>
        <a href="/" className="text-sm mt-4 inline-block" style={{ color: "var(--accent)" }}>Back to home</a>
      </div>
    </main>
  );

  const isManager = agent.role === "manager";
  const isEigen = agent.tee === "Intel TDX" || agent.endpoint?.includes("34.142.184") || agent.endpoint?.includes("34.16.84");

  return (
    <main className="min-h-screen">
      <Nav active="/agent" />

      <div className="max-w-[1120px] mx-auto px-4 sm:px-6">
        {/* Agent Identity */}
        <section className="pt-12 pb-8" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-3 mb-3">
                <h1 className="text-2xl font-bold" style={{ fontFamily: "var(--font-display)" }}>{agent.agent_id}</h1>
                <span className={`badge ${isManager ? "badge-pending" : "badge-live"}`}>{agent.role}</span>
                {health && !healthError ? (
                  <span className="flex items-center gap-1.5 text-xs" style={{ color: "var(--success)" }}>
                    <span className="live-dot" /> Online
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-muted)" }}>
                    <span className="live-dot" style={{ background: "var(--text-muted)", boxShadow: "none", animation: "none" }} /> Offline
                  </span>
                )}
              </div>
              {agent.strategy && <p className="text-sm" style={{ color: "var(--text-muted)" }}>Strategy: <span style={{ color: "var(--accent)" }}>{agent.strategy}</span></p>}
              {agent.endpoint && <p className="text-xs mt-1" style={{ color: "var(--text-muted)", opacity: 0.6 }}>{agent.endpoint}</p>}
            </div>
            {agent.owner && (
              <a href={`https://basescan.org/address/${agent.owner}`} target="_blank" rel="noopener noreferrer" className="btn-ghost text-xs">
                Owner: {agent.owner.slice(0, 6)}...{agent.owner.slice(-4)}
              </a>
            )}
          </div>
        </section>

        {/* Stats */}
        <section className="py-8" style={{ borderBottom: "1px solid var(--border)" }}>
          <p className="section-label mb-4">Live Stats</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: "Status", value: health && !healthError ? "Healthy" : "Unreachable", color: health && !healthError ? "var(--success)" : "var(--critical)" },
              { label: "Jobs Completed", value: health?.jobs_completed ?? "...", color: "var(--text)" },
              { label: "Uptime", value: health?.uptime ? formatUptime(health.uptime) : "...", color: "var(--text)" },
              { label: "Job Types", value: (health?.job_types as string[])?.length ?? 1, color: "var(--text)" },
            ].map((s) => (
              <div key={s.label} className="glass p-4">
                <p className="section-label mb-1">{s.label}</p>
                <p className="text-xl font-bold" style={{ fontFamily: "var(--font-display)", color: s.color as string }}>{String(s.value)}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Infrastructure */}
        <section className="py-8" style={{ borderBottom: "1px solid var(--border)" }}>
          <p className="section-label mb-4">Infrastructure</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="glass p-4">
              <p className="section-label mb-1">Deployment</p>
              <p className="text-sm font-bold">{agent.endpoint?.includes("railway") ? "Railway" : isEigen ? "EigenCompute (Intel TDX TEE)" : "Self-hosted"}</p>
              {isEigen && <a href="https://verify-sepolia.eigencloud.xyz/app/0x7Fc30484aCF81961bc766FE07281cf2684A33ffE" target="_blank" rel="noopener noreferrer" className="text-xs mt-1 block" style={{ color: "var(--accent)" }}>View TEE attestation</a>}
            </div>
            <div className="glass p-4">
              <p className="section-label mb-1">Source</p>
              <p className="text-sm font-bold">{agent.source || "API registration"}</p>
              {agent.registered_at && <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Registered: {new Date(agent.registered_at * 1000).toLocaleDateString()}</p>}
            </div>
            {agent.tee && (
              <div className="glass p-4 relative overflow-hidden">
                <div className="absolute top-0 left-0 right-0 h-[2px]" style={{ background: "linear-gradient(90deg, var(--success), transparent)" }} />
                <p className="section-label mb-1">TEE Attestation</p>
                <p className="text-sm font-bold" style={{ color: "var(--success)" }}>{agent.tee}</p>
                <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Hardware-attested execution. Scoring cannot be tampered with.</p>
              </div>
            )}
            <div className="glass p-4">
              <p className="section-label mb-1">Job Types</p>
              <div className="flex flex-wrap gap-2 mt-1">
                {(health?.job_types || ["code-verification"]).map((t: string) => (
                  <span key={t} className="badge" style={{ background: "var(--highlight)", color: "var(--accent)" }}>{t}</span>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* On-Chain Identity */}
        <section className="py-8" style={{ borderBottom: "1px solid var(--border)" }}>
          <p className="section-label mb-4">On-Chain Identity</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {[
              { label: "AgentRegistry", link: "https://basescan.org/address/0xf80DA8B7687685Bc96bf521085Ac1C0eea64bbDd", desc: "Permanent on-chain registration" },
              { label: "AgentScorer", link: "https://basescan.org/address/0x4e588353E7f247782A6109Fff3BA284a20D88c0F", desc: "Quality ratings on-chain" },
              ...(agent.owner ? [{ label: "Owner Wallet", link: `https://basescan.org/address/${agent.owner}`, desc: agent.owner }] : []),
              { label: "ERC-8004 Reputation", link: "https://basescan.org/address/0x8004BAa17C55a88189AE136b182e5fdA19dE9b63", desc: "Portable reputation across ecosystem" },
            ].map((item) => (
              <a key={item.label} href={item.link} target="_blank" rel="noopener noreferrer" className="glass p-4 block transition-all hover:scale-[1.005]">
                <p className="section-label mb-1">{item.label}</p>
                <p className="text-sm" style={{ color: "var(--accent)" }}>View on Basescan</p>
                <p className="text-xs mt-1 break-all" style={{ color: "var(--text-muted)" }}>{item.desc}</p>
              </a>
            ))}
          </div>
        </section>

        {/* Job History */}
        <section className="py-8" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="flex items-center justify-between mb-4">
            <p className="section-label">Job History</p>
            <span className="text-xs" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>{completedJobs.length} jobs</span>
          </div>
          {completedJobs.length > 0 ? (
            <div className="glass overflow-hidden">
              {completedJobs.map((job, i) => (
                <div key={i} className="flex items-center justify-between px-5 py-3 text-sm transition-colors" style={{ borderBottom: "1px solid var(--border)" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "var(--highlight)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
                  <div className="flex items-center gap-3">
                    <span className={`badge ${job.passed ? "badge-live" : "badge-failed"}`}>{job.passed ? "Clean" : "Issues Found"}</span>
                    <span className="badge" style={{ background: "var(--highlight)", color: "var(--accent)" }}>{job.job_type}</span>
                    <span style={{ color: "var(--text-muted)" }}>{job.issues_count} issues</span>
                  </div>
                  <div className="flex items-center gap-4 text-xs" style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                    <span>{(job.confidence * 100).toFixed(0)}%</span>
                    <span>{job.mode}</span>
                    <span>{new Date(job.created_at).toLocaleTimeString()}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>No completed jobs yet.</p>
          )}
        </section>

        {/* Health JSON */}
        {agent.endpoint && (
          <section className="py-8" style={{ borderBottom: "1px solid var(--border)" }}>
            <p className="section-label mb-4">Live Health Check</p>
            <div className="glass p-5">
              <pre className="text-xs overflow-x-auto" style={{ fontFamily: "var(--font-mono)", color: "var(--success)" }}>
                {health ? JSON.stringify(health, null, 2) : "Unable to reach agent endpoint"}
              </pre>
            </div>
            <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
              Live data from <a href={`${agent.endpoint}/health`} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>{agent.endpoint}/health</a>
            </p>
          </section>
        )}

        <footer className="py-10 text-center">
          <a href="/leaderboard" className="text-sm" style={{ color: "var(--accent)" }}>Back to leaderboard</a>
        </footer>
      </div>
    </main>
  );
}
