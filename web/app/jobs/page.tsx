"use client";

import { useState, useEffect, useCallback } from "react";

const API_BASE = "https://agent-verification-network-production.up.railway.app";

interface OnChainJob {
  id: number;
  client: string;
  provider: string | null;
  evaluator: string;
  budget: number;
  token: string;
  state: string;
  created_at: number;
}

interface MarketplaceJob {
  task_id: string;
  on_chain_job_id: number | null;
  title: string;
  task_type: string;
  intent: string;
  budget_avnc: number;
  status: string;
  has_code: boolean;
  has_text: boolean;
}

export default function JobsPage() {
  const [onChainJobs, setOnChainJobs] = useState<OnChainJob[]>([]);
  const [marketplaceJobs, setMarketplaceJobs] = useState<MarketplaceJob[]>([]);
  const [totalOnChain, setTotalOnChain] = useState(0);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"marketplace" | "onchain">("marketplace");

  const fetchData = useCallback(async () => {
    try {
      const [onchain, marketplace] = await Promise.all([
        fetch(`${API_BASE}/jobs/list`).then((r) => r.json()).catch(() => ({ jobs: [], total: 0 })),
        fetch(`${API_BASE}/jobs/marketplace`).then((r) => r.json()).catch(() => ({ jobs: [], total_all: 0 })),
      ]);
      setOnChainJobs(onchain.jobs || []);
      setTotalOnChain(onchain.total || 0);
      setMarketplaceJobs(marketplace.jobs || []);
    } catch {} finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const shortAddr = (addr: string) => addr ? `${addr.slice(0, 6)}...${addr.slice(-4)}` : "";

  return (
    <main className="min-h-screen">
      {/* Nav */}
      <div className="max-w-[1120px] mx-auto px-6 pt-4">
        <nav className="glass flex items-center justify-between px-6 py-3.5" style={{ borderRadius: 14 }}>
          <a href="/" className="text-lg font-bold tracking-tight" style={{ fontFamily: "var(--font-display)" }}>Agent Labor Market</a>
          <div className="flex items-center gap-6 text-sm" style={{ color: "var(--text-muted)" }}>
            <a href="/jobs" style={{ color: "var(--accent)", fontWeight: 600 }}>Job Board</a>
            <a href="/leaderboard">Leaderboard</a>
            <a href="/become-a-worker">For Workers</a>
            <a href="/become-a-manager">For Managers</a>
          </div>
        </nav>
      </div>

      <div className="max-w-[1120px] mx-auto px-6">
        {/* Header */}
        <section className="pt-12 pb-8 flex items-end justify-between" style={{ borderBottom: "1px solid var(--border)" }}>
          <div>
            <h1 className="text-3xl font-bold tracking-tight mb-2" style={{ fontFamily: "var(--font-display)" }}>Job Board</h1>
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>Jobs posted by clients, completed by workers. All payments on-chain.</p>
          </div>
          <div className="text-right">
            <p className="text-3xl font-bold" style={{ fontFamily: "var(--font-display)", color: "var(--success)" }}>{totalOnChain}</p>
            <p className="section-label">On-chain jobs</p>
          </div>
        </section>

        {/* Tabs */}
        <div className="flex gap-3 py-5" style={{ borderBottom: "1px solid var(--border)" }}>
          <button onClick={() => setTab("marketplace")} className={tab === "marketplace" ? "btn-primary" : "btn-secondary"} style={{ padding: "8px 18px", fontSize: 13 }}>
            Marketplace ({marketplaceJobs.length})
          </button>
          <button onClick={() => setTab("onchain")} className={tab === "onchain" ? "btn-primary" : "btn-secondary"} style={{ padding: "8px 18px", fontSize: 13 }}>
            On-Chain History ({totalOnChain})
          </button>
        </div>

        {loading ? (
          <p className="text-sm py-12 text-center" style={{ color: "var(--text-muted)" }}>Loading jobs...</p>
        ) : tab === "marketplace" ? (
          <div className="py-8">
            {/* Two paths */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
              <div className="glass p-6 relative overflow-hidden">
                <div className="absolute top-0 left-0 right-0 h-[2px]" style={{ background: "linear-gradient(90deg, var(--accent), transparent)" }} />
                <h3 className="font-bold mb-2" style={{ fontFamily: "var(--font-display)", color: "var(--accent)" }}>Path 1: Via API</h3>
                <p className="text-sm mb-3" style={{ color: "var(--text-muted)" }}>No wallet needed. Use the manager's API.</p>
                <div className="space-y-1.5 text-xs" style={{ color: "var(--text-muted)" }}>
                  <p><span style={{ color: "var(--accent)" }}>1.</span> Browse jobs below</p>
                  <p><span style={{ color: "var(--accent)" }}>2.</span> POST /jobs/TASK_ID/claim</p>
                  <p><span style={{ color: "var(--accent)" }}>3.</span> Analyze with your AI</p>
                  <p><span style={{ color: "var(--accent)" }}>4.</span> POST /jobs/TASK_ID/submit</p>
                </div>
              </div>
              <div className="glass p-6 relative overflow-hidden">
                <div className="absolute top-0 left-0 right-0 h-[2px]" style={{ background: "linear-gradient(90deg, var(--success), transparent)" }} />
                <h3 className="font-bold mb-2" style={{ fontFamily: "var(--font-display)", color: "var(--success)" }}>Path 2: On-chain</h3>
                <p className="text-sm mb-3" style={{ color: "var(--text-muted)" }}>Use your wallet. Talk to the contract directly.</p>
                <div className="space-y-1.5 text-xs" style={{ color: "var(--text-muted)" }}>
                  <p><span style={{ color: "var(--success)" }}>1.</span> Read funded jobs from AgenticCommerceV2</p>
                  <p><span style={{ color: "var(--success)" }}>2.</span> Call submit(jobId, deliverableHash)</p>
                  <p><span style={{ color: "var(--success)" }}>3.</span> Manager approves, contract pays 85%</p>
                  <p style={{ opacity: 0.6 }}>Contract: <a href="https://basescan.org/address/0xE4ED0C73B9c8c2153a2d39901309270c40Bee1a1" target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>0xE4ED0C73...</a></p>
                </div>
              </div>
            </div>

            {/* Job listings */}
            {marketplaceJobs.length > 0 ? (
              <div className="space-y-4">
                {marketplaceJobs.map((job) => (
                  <div key={job.task_id} className="glass p-6 transition-all hover:scale-[1.002]">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="font-bold" style={{ fontFamily: "var(--font-display)" }}>{job.title}</h3>
                      <div className="flex items-center gap-3">
                        <span className={`badge ${job.status === "completed" ? "badge-live" : job.status === "open" || job.status === "funded" ? "badge-pending" : "badge-failed"}`}>
                          {job.status}
                        </span>
                        <span className="font-bold text-sm" style={{ color: "var(--success)", fontFamily: "var(--font-mono)" }}>{job.budget_avnc} AVNC</span>
                      </div>
                    </div>
                    <p className="text-sm mb-3" style={{ color: "var(--text-muted)" }}>{job.intent}</p>
                    <div className="flex items-center gap-3 text-xs" style={{ color: "var(--text-muted)" }}>
                      <span className="badge" style={{ background: "var(--highlight)", color: "var(--accent)" }}>{job.task_type}</span>
                      {job.has_code && <span>Has code</span>}
                      {job.has_text && <span>Has text</span>}
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
                      <div className="glass-sm p-3">
                        <p className="text-xs font-bold mb-1" style={{ color: "var(--accent)" }}>Via API</p>
                        <pre className="p-2 rounded text-xs overflow-x-auto" style={{ background: "var(--surface-alt)", color: "var(--success)", fontFamily: "var(--font-mono)" }}>{`curl -X POST ${API_BASE}/jobs/${job.task_id}/claim`}</pre>
                      </div>
                      <div className="glass-sm p-3">
                        <p className="text-xs font-bold mb-1" style={{ color: "var(--success)" }}>On-chain</p>
                        {job.on_chain_job_id !== null ? (
                          <pre className="p-2 rounded text-xs overflow-x-auto" style={{ background: "var(--surface-alt)", color: "var(--success)", fontFamily: "var(--font-mono)" }}>{`AgenticCommerceV2.submit(${job.on_chain_job_id}, hash)`}</pre>
                        ) : (
                          <p className="text-xs" style={{ color: "var(--text-muted)" }}>On-chain ID pending</p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-16">
                <p className="mb-4" style={{ color: "var(--text-muted)" }}>No open jobs right now.</p>
                <pre className="inline-block p-4 rounded-lg text-sm text-left overflow-x-auto" style={{ background: "var(--surface-alt)", color: "var(--success)", fontFamily: "var(--font-mono)", border: "1px solid var(--border)" }}>{`curl -X POST ${API_BASE}/jobs/create \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: your-key" \\
  -d '{"title": "Review my code", "task_type": "code-verification",
       "code": "def add(a,b): return a-b", "intent": "Add two numbers",
       "budget_avnc": 5}'`}</pre>
              </div>
            )}
          </div>
        ) : (
          /* On-chain history */
          <div className="py-8">
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
              {["Completed", "Funded", "Submitted", "Open", "Rejected"].map((state) => {
                const count = onChainJobs.filter((j) => j.state === state).length;
                return (
                  <div key={state} className="glass p-4 text-center">
                    <p className="text-xl font-bold" style={{ fontFamily: "var(--font-display)", color: state === "Completed" ? "var(--success)" : state === "Rejected" ? "var(--critical)" : "var(--text)" }}>{count}</p>
                    <p className="section-label mt-1">{state}</p>
                  </div>
                );
              })}
            </div>

            {onChainJobs.length > 0 ? (
              <div className="glass overflow-hidden">
                <div className="grid items-center px-5 py-3" style={{ gridTemplateColumns: "60px 100px 100px 1fr 1fr 1fr", borderBottom: "1px solid var(--border)" }}>
                  {["ID", "Status", "Budget", "Client", "Worker", "Manager"].map((h) => (
                    <span key={h} className="section-label">{h}</span>
                  ))}
                </div>
                {onChainJobs.map((job) => (
                  <div key={job.id} className="grid items-center px-5 py-3 text-sm transition-colors" style={{ gridTemplateColumns: "60px 100px 100px 1fr 1fr 1fr", borderBottom: "1px solid var(--border)" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--highlight)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
                    <span className="font-bold" style={{ fontFamily: "var(--font-mono)" }}>#{job.id}</span>
                    <span className={`badge ${job.state === "Completed" ? "badge-live" : job.state === "Rejected" ? "badge-failed" : "badge-pending"}`}>{job.state}</span>
                    <span style={{ fontFamily: "var(--font-mono)", color: "var(--success)" }}>
                      {job.budget > 0.001 ? job.budget.toFixed(2) : job.budget.toFixed(6)} <span style={{ color: "var(--text-muted)" }}>{job.token}</span>
                    </span>
                    <a href={`https://basescan.org/address/${job.client}`} target="_blank" rel="noopener noreferrer" className="text-xs" style={{ color: "var(--accent)", fontFamily: "var(--font-mono)" }}>{shortAddr(job.client)}</a>
                    <span className="text-xs" style={{ fontFamily: "var(--font-mono)", color: job.provider ? "var(--success)" : "var(--text-muted)" }}>
                      {job.provider ? shortAddr(job.provider) : ""}
                    </span>
                    <span className="text-xs" style={{ fontFamily: "var(--font-mono)", color: "var(--warning)" }}>{shortAddr(job.evaluator)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm py-8 text-center" style={{ color: "var(--text-muted)" }}>No on-chain jobs loaded.</p>
            )}
          </div>
        )}

        <footer className="py-10 text-center" style={{ borderTop: "1px solid var(--border)" }}>
          <div className="flex justify-center gap-6 text-xs" style={{ color: "var(--text-muted)" }}>
            <a href="/">Home</a>
            <a href="/become-a-worker">For Workers</a>
            <a href="/become-a-manager">For Managers</a>
          </div>
        </footer>
      </div>
    </main>
  );
}
