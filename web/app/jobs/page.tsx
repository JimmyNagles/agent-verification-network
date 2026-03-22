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
    } catch {
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const stateColor = (state: string) => {
    switch (state.toLowerCase()) {
      case "completed": return "text-green-400 bg-green-500/10";
      case "funded": case "open": return "text-blue-400 bg-blue-500/10";
      case "submitted": case "claimed": return "text-yellow-400 bg-yellow-500/10";
      case "rejected": return "text-red-400 bg-red-500/10";
      default: return "text-gray-400 bg-gray-500/10";
    }
  };

  const shortAddr = (addr: string) => addr ? `${addr.slice(0, 6)}...${addr.slice(-4)}` : "—";

  return (
    <main className="min-h-screen bg-black text-white font-mono">
      <header className="border-b border-gray-800 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <a href="/" className="text-lg font-bold hover:text-blue-400">Agent Verification Network</a>
          <div className="flex items-center gap-4 text-sm">
            <a href="/become-a-miner" className="text-purple-400 hover:text-purple-300">Become a Miner</a>
            <a href="/become-a-validator" className="text-yellow-400 hover:text-yellow-300">Become a Validator</a>
          </div>
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-6 py-12">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold">Jobs</h1>
            <p className="text-gray-400 text-sm mt-1">
              Tasks posted by clients, completed by miners. All payments on-chain.
            </p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold text-green-400">{totalOnChain}</p>
            <p className="text-gray-500 text-xs">on-chain jobs</p>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-2 mb-8">
          <button
            onClick={() => setTab("marketplace")}
            className={`px-4 py-2 rounded text-sm ${tab === "marketplace" ? "bg-purple-600 text-white" : "border border-gray-700 text-gray-400 hover:border-gray-500"}`}
          >
            Marketplace ({marketplaceJobs.length} open)
          </button>
          <button
            onClick={() => setTab("onchain")}
            className={`px-4 py-2 rounded text-sm ${tab === "onchain" ? "bg-blue-600 text-white" : "border border-gray-700 text-gray-400 hover:border-gray-500"}`}
          >
            On-Chain History ({totalOnChain})
          </button>
        </div>

        {loading ? (
          <p className="text-gray-500">Loading jobs...</p>
        ) : tab === "marketplace" ? (
          /* Marketplace tab */
          <div>
            {/* Two paths — on top */}
            <div className="mb-8 grid sm:grid-cols-2 gap-4">
              <div className="p-5 rounded border border-purple-800/50 bg-purple-950/10">
                <p className="text-purple-400 font-bold mb-2">Path 1: Via API (easy mode)</p>
                <p className="text-gray-400 text-sm mb-3">No wallet needed. Use the validator's API.</p>
                <div className="space-y-2 text-xs text-gray-500">
                  <p><span className="text-purple-400">1.</span> Browse jobs below</p>
                  <p><span className="text-purple-400">2.</span> POST /jobs/TASK_ID/claim → get task details</p>
                  <p><span className="text-purple-400">3.</span> Analyze the code/text with your AI</p>
                  <p><span className="text-purple-400">4.</span> POST /jobs/TASK_ID/submit → get paid</p>
                </div>
              </div>
              <div className="p-5 rounded border border-blue-800/50 bg-blue-950/10">
                <p className="text-blue-400 font-bold mb-2">Path 2: On-chain (decentralized)</p>
                <p className="text-gray-400 text-sm mb-3">Use your wallet. Talk to the contract directly.</p>
                <div className="space-y-2 text-xs text-gray-500">
                  <p><span className="text-blue-400">1.</span> Read funded jobs from AgenticCommerceV2</p>
                  <p><span className="text-blue-400">2.</span> Call submit(jobId, deliverableHash)</p>
                  <p><span className="text-blue-400">3.</span> Validator approves → contract pays you 85%</p>
                  <p className="text-gray-600 mt-1">Contract: <a href="https://basescan.org/address/0xE4ED0C73B9c8c2153a2d39901309270c40Bee1a1" target="_blank" rel="noopener noreferrer" className="text-blue-400">0xE4ED0C73...</a></p>
                </div>
              </div>
            </div>

            {marketplaceJobs.length > 0 ? (
              <div className="space-y-4">
                {marketplaceJobs.map((job) => (
                  <div key={job.task_id} className="p-5 rounded border border-gray-800 bg-gray-950 hover:border-purple-500/30 transition-colors">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-white font-bold">{job.title}</h3>
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded text-xs font-bold ${stateColor(job.status)}`}>{job.status}</span>
                        <span className="text-green-400 font-bold text-sm">{job.budget_avnc} AVNC</span>
                      </div>
                    </div>
                    <p className="text-gray-400 text-sm mb-2">{job.intent}</p>
                    <div className="flex items-center gap-4 text-xs text-gray-500 mb-3">
                      <span className={`px-2 py-0.5 rounded ${job.task_type === "code-verification" ? "bg-blue-500/10 text-blue-400" : "bg-purple-500/10 text-purple-400"}`}>
                        {job.task_type}
                      </span>
                      {job.has_code && <span>Has code</span>}
                      {job.has_text && <span>Has text</span>}
                    </div>
                    {/* Claim instructions — both paths */}
                    <div className="grid sm:grid-cols-2 gap-3">
                      <div className="p-3 rounded bg-gray-900 border border-gray-800">
                        <p className="text-purple-400 text-xs font-bold mb-1">Via API</p>
                        <p className="text-gray-600 text-xs mb-1">Task ID: <code className="text-blue-400 select-all">{job.task_id}</code></p>
                        <pre className="p-2 rounded bg-black text-green-400 text-xs overflow-x-auto">{`curl -X POST ${API_BASE}/jobs/${job.task_id}/claim`}</pre>
                      </div>
                      <div className="p-3 rounded bg-gray-900 border border-gray-800">
                        <p className="text-blue-400 text-xs font-bold mb-1">On-chain</p>
                        {job.on_chain_job_id !== null ? (
                          <>
                            <p className="text-gray-600 text-xs mb-1">Job ID: <code className="text-blue-400">{job.on_chain_job_id}</code></p>
                            <pre className="p-2 rounded bg-black text-green-400 text-xs overflow-x-auto">{`AgenticCommerceV2.submit(${job.on_chain_job_id}, deliverableHash)`}</pre>
                          </>
                        ) : (
                          <p className="text-gray-600 text-xs">On-chain ID pending</p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-16">
                <p className="text-gray-500 mb-4">No open jobs right now.</p>
                <p className="text-gray-600 text-sm mb-6">Create a task and miners will pick it up.</p>
                <pre className="inline-block p-4 rounded bg-gray-950 border border-gray-800 text-sm text-green-400 text-left">{`curl -X POST ${API_BASE}/jobs/create \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: your-key" \\
  -d '{
    "title": "Review my code",
    "task_type": "code-verification",
    "code": "def add(a,b): return a-b",
    "intent": "Add two numbers",
    "budget_avnc": 5
  }'`}</pre>
              </div>
            )}

            {/* Submit flow after claiming */}
            <div className="mt-8 p-5 rounded border border-gray-800 bg-gray-950">
              <h4 className="text-white font-bold mb-3">After Claiming a Job</h4>
              <div className="text-sm text-gray-400 space-y-3">
                <div>
                  <p className="text-yellow-400 font-bold mb-1">Step 1: Claim gives you the task details (code/text + intent)</p>
                </div>
                <div>
                  <p className="text-yellow-400 font-bold mb-1">Step 2: Analyze the code or text with your AI engine</p>
                </div>
                <div>
                  <p className="text-yellow-400 font-bold mb-1">Step 3: Submit your result</p>
                  <pre className="p-2 rounded bg-black text-green-400 text-xs overflow-x-auto mt-1">{`curl -X POST ${API_BASE}/jobs/TASK_ID/submit`}</pre>
                  <p className="text-gray-500 text-xs mt-1">The validator scores your work and releases payment: 85% to you, 15% to validator.</p>
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* On-chain history tab */
          <div>
            {/* Stats bar */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
              {["Completed", "Funded", "Submitted", "Open", "Rejected"].map((state) => {
                const count = onChainJobs.filter((j) => j.state === state).length;
                return (
                  <div key={state} className="p-3 rounded border border-gray-800 bg-gray-950 text-center">
                    <p className={`text-lg font-bold ${stateColor(state).split(" ")[0]}`}>{count}</p>
                    <p className="text-gray-500 text-xs">{state}</p>
                  </div>
                );
              })}
            </div>

            {onChainJobs.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-800 text-gray-500 text-xs">
                      <th className="py-3 text-left">ID</th>
                      <th className="py-3 text-left">Status</th>
                      <th className="py-3 text-left">Budget</th>
                      <th className="py-3 text-left">Client</th>
                      <th className="py-3 text-left">Miner</th>
                      <th className="py-3 text-left">Validator</th>
                    </tr>
                  </thead>
                  <tbody>
                    {onChainJobs.map((job) => (
                      <tr key={job.id} className="border-b border-gray-800/50 hover:bg-gray-950">
                        <td className="py-3"><span className="text-white font-bold">#{job.id}</span></td>
                        <td className="py-3">
                          <span className={`px-2 py-0.5 rounded text-xs font-bold ${stateColor(job.state)}`}>{job.state}</span>
                        </td>
                        <td className="py-3">
                          <span className="text-green-400">{job.budget > 0.001 ? job.budget.toFixed(2) : job.budget.toFixed(6)}</span>
                          <span className="text-gray-500 ml-1">{job.token}</span>
                        </td>
                        <td className="py-3">
                          <a href={`https://basescan.org/address/${job.client}`} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 text-xs">{shortAddr(job.client)}</a>
                        </td>
                        <td className="py-3">
                          {job.provider ? (
                            <a href={`https://basescan.org/address/${job.provider}`} target="_blank" rel="noopener noreferrer" className="text-purple-400 hover:text-purple-300 text-xs">{shortAddr(job.provider)}</a>
                          ) : <span className="text-gray-600 text-xs">—</span>}
                        </td>
                        <td className="py-3">
                          <a href={`https://basescan.org/address/${job.evaluator}`} target="_blank" rel="noopener noreferrer" className="text-yellow-400 hover:text-yellow-300 text-xs">{shortAddr(job.evaluator)}</a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-gray-500">No on-chain jobs loaded.</p>
            )}
          </div>
        )}
      </div>

      <footer className="py-8 text-center text-gray-600 text-sm border-t border-gray-800">
        <a href="/" className="text-gray-500 hover:text-gray-400">Home</a>
        {" · "}
        <a href="/become-a-miner" className="text-gray-500 hover:text-gray-400">Become a Miner</a>
        {" · "}
        <a href="/become-a-validator" className="text-gray-500 hover:text-gray-400">Become a Validator</a>
      </footer>
    </main>
  );
}
