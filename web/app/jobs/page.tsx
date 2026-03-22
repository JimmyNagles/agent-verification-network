"use client";

import { useState, useEffect, useCallback } from "react";

const API_BASE = "https://agent-verification-network-production.up.railway.app";

interface Job {
  id: number;
  client: string;
  provider: string | null;
  evaluator: string;
  budget: number;
  token: string;
  state: string;
  created_at: number;
}

interface JobsData {
  jobs: Job[];
  total: number;
  contract: string;
  chain: string;
}

export default function JobsPage() {
  const [data, setData] = useState<JobsData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchJobs = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/jobs/list`);
      const d = await resp.json();
      setData(d);
    } catch {
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 30000);
    return () => clearInterval(interval);
  }, [fetchJobs]);

  const stateColor = (state: string) => {
    switch (state) {
      case "Completed": return "text-green-400 bg-green-500/10";
      case "Funded": return "text-blue-400 bg-blue-500/10";
      case "Submitted": return "text-yellow-400 bg-yellow-500/10";
      case "Open": return "text-gray-400 bg-gray-500/10";
      case "Rejected": return "text-red-400 bg-red-500/10";
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
            <a href="https://github.com/JimmyNagles/agent-verification-network" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300">GitHub</a>
          </div>
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-6 py-12">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold">On-Chain Jobs</h1>
            <p className="text-gray-400 text-sm mt-1">
              All jobs from AgenticCommerceV2 on Base Mainnet — real transactions, real payments.
            </p>
          </div>
          {data && (
            <div className="text-right">
              <p className="text-2xl font-bold text-green-400">{data.total}</p>
              <p className="text-gray-500 text-xs">total jobs</p>
            </div>
          )}
        </div>

        {/* Stats bar */}
        {data && data.jobs.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-8">
            {["Completed", "Funded", "Submitted", "Open", "Rejected"].map((state) => {
              const count = data.jobs.filter((j) => j.state === state).length;
              return (
                <div key={state} className="p-3 rounded border border-gray-800 bg-gray-950 text-center">
                  <p className={`text-lg font-bold ${stateColor(state).split(" ")[0]}`}>{count}</p>
                  <p className="text-gray-500 text-xs">{state}</p>
                </div>
              );
            })}
          </div>
        )}

        {/* Jobs table */}
        {loading ? (
          <p className="text-gray-500">Loading jobs from Base Mainnet...</p>
        ) : data && data.jobs.length > 0 ? (
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
                {data.jobs.map((job) => (
                  <tr key={job.id} className="border-b border-gray-800/50 hover:bg-gray-950">
                    <td className="py-3">
                      <span className="text-white font-bold">#{job.id}</span>
                    </td>
                    <td className="py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-bold ${stateColor(job.state)}`}>
                        {job.state}
                      </span>
                    </td>
                    <td className="py-3">
                      <span className="text-green-400">{job.budget > 0.001 ? job.budget.toFixed(2) : job.budget.toFixed(6)}</span>
                      <span className="text-gray-500 ml-1">{job.token}</span>
                    </td>
                    <td className="py-3">
                      <a href={`https://basescan.org/address/${job.client}`} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 text-xs">
                        {shortAddr(job.client)}
                      </a>
                    </td>
                    <td className="py-3">
                      {job.provider ? (
                        <a href={`https://basescan.org/address/${job.provider}`} target="_blank" rel="noopener noreferrer" className="text-purple-400 hover:text-purple-300 text-xs">
                          {shortAddr(job.provider)}
                        </a>
                      ) : (
                        <span className="text-gray-600 text-xs">—</span>
                      )}
                    </td>
                    <td className="py-3">
                      <a href={`https://basescan.org/address/${job.evaluator}`} target="_blank" rel="noopener noreferrer" className="text-yellow-400 hover:text-yellow-300 text-xs">
                        {shortAddr(job.evaluator)}
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-gray-500">No jobs found.</p>
        )}

        {/* Contract link */}
        {data?.contract && (
          <div className="mt-8 p-4 rounded border border-gray-800 bg-gray-950 text-center">
            <p className="text-gray-500 text-xs mb-1">AgenticCommerceV2 on Base Mainnet</p>
            <a href={`https://basescan.org/address/${data.contract}`} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 text-sm">
              {data.contract}
            </a>
            <p className="text-gray-600 text-xs mt-1">All jobs are on-chain. Verify any transaction on Basescan.</p>
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
