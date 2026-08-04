"use client";

import React, { useEffect, useState } from "react";
import {
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  FlaskConical,
  HelpCircle,
  Loader2,
  ShieldCheck,
} from "lucide-react";
import {
  fetchBenchmarkScorecard,
  BenchmarkScorecardResponse,
} from "@/lib/apiSynthetic";

interface BenchmarkScorecardCardProps {
  datasetId: string;
}

export default function BenchmarkScorecardCard({
  datasetId,
}: BenchmarkScorecardCardProps) {
  const [scorecardData, setScorecardData] =
    useState<BenchmarkScorecardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    async function loadScorecard() {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchBenchmarkScorecard(datasetId);
        if (isMounted) setScorecardData(data);
      } catch (err: unknown) {
        if (isMounted) {
          setError(
            err instanceof Error ? err.message : "Failed to load scorecard"
          );
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    }
    loadScorecard();
    return () => {
      isMounted = false;
    };
  }, [datasetId]);

  if (loading) {
    return (
      <div className="mb-8 p-6 rounded-2xl bg-indigo-50/50 border border-indigo-100 flex items-center justify-center gap-3 text-sm text-indigo-700">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span>Evaluating statistical diagnosis against academic ground-truth rules...</span>
      </div>
    );
  }

  if (error || !scorecardData || !scorecardData.is_benchmark_dataset) {
    return null;
  }

  const { scorecard, accuracy_pct, total_columns_evaluated, correct_mechanisms } =
    scorecardData;

  if (scorecard.length === 0) {
    return (
      <div className="mb-8 p-6 rounded-2xl bg-gradient-to-r from-indigo-500/10 to-blue-500/10 border border-indigo-200/60 flex items-center gap-4">
        <div className="w-10 h-10 rounded-xl bg-indigo-600 text-white flex items-center justify-center shrink-0 shadow-sm">
          <FlaskConical className="w-5 h-5" />
        </div>
        <div>
          <h4 className="text-sm font-bold text-gray-900">
            Synthetic Benchmark Active ({scorecardData.dataset_filename})
          </h4>
          <p className="text-xs text-gray-600 mt-0.5">
            Start or run the statistical diagnosis job below to view the automated Ground-Truth vs. AI Diagnosis scorecard.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mb-8 rounded-3xl bg-gradient-to-br from-indigo-900 via-slate-900 to-blue-950 text-white p-6 sm:p-8 shadow-xl border border-indigo-500/30 overflow-hidden relative">
      {/* Decorative glow */}
      <div
        aria-hidden
        className="absolute -right-16 -top-16 w-64 h-64 rounded-full bg-indigo-500/10 blur-3xl pointer-events-none"
      />

      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-6 border-b border-indigo-500/30 relative z-10">
        <div className="flex items-center gap-3.5">
          <div className="w-12 h-12 rounded-2xl bg-indigo-500/20 backdrop-blur-md border border-indigo-400/30 flex items-center justify-center text-indigo-300 shrink-0">
            <FlaskConical className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-indigo-300">
                Ground-Truth Benchmark Scorecard
              </span>
              <span className="px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-200 text-[10px] font-bold border border-indigo-400/20">
                Academic Evaluation
              </span>
            </div>
            <h3 className="text-xl font-bold tracking-tight text-white mt-0.5">
              {scorecardData.dataset_filename}
            </h3>
          </div>
        </div>

        {/* Overall Score Pill */}
        <div className="flex items-center gap-3 px-4 py-2.5 rounded-2xl bg-white/10 backdrop-blur-md border border-white/15">
          <ShieldCheck className="w-6 h-6 text-emerald-400 shrink-0" />
          <div>
            <div className="text-xs text-indigo-200 font-medium">
              Statistical Accuracy
            </div>
            <div className="text-lg font-black text-white tabular-nums">
              {accuracy_pct}% ({correct_mechanisms}/{total_columns_evaluated} matches)
            </div>
          </div>
        </div>
      </div>

      {/* Scorecard Table */}
      <div className="mt-6 overflow-x-auto relative z-10">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-indigo-500/30 text-[11px] font-semibold text-indigo-300 uppercase tracking-wider">
              <th className="pb-3 px-3">Column</th>
              <th className="pb-3 px-3">Ground Truth</th>
              <th className="pb-3 px-3">AI / Stat Diagnosis</th>
              <th className="pb-3 px-3">Match Status</th>
              <th className="pb-3 px-3 text-right">Driver / Rule Check</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-indigo-500/20 text-sm">
            {scorecard.map((item) => {
              const isMatch = item.is_match;
              return (
                <tr
                  key={item.target_column}
                  className="hover:bg-white/5 transition-colors"
                >
                  <td className="py-3.5 px-3 font-bold text-white tabular-nums">
                    {item.target_column}
                  </td>
                  <td className="py-3.5 px-3">
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold uppercase tracking-wide bg-indigo-500/30 text-indigo-200 border border-indigo-400/30">
                      {item.ground_truth_mechanism}
                    </span>
                    {item.ground_truth_rate && (
                      <span className="ml-2 text-xs text-indigo-300 tabular-nums">
                        ({Math.round(item.ground_truth_rate * 100)}%)
                      </span>
                    )}
                  </td>
                  <td className="py-3.5 px-3 font-semibold text-indigo-100">
                    {item.diagnosed_mechanism || "Pending"}
                  </td>
                  <td className="py-3.5 px-3">
                    {isMatch ? (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                        <span>{item.match_status}</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                        <span>{item.match_status}</span>
                      </span>
                    )}
                  </td>
                  <td className="py-3.5 px-3 text-right text-xs text-indigo-200 max-w-xs truncate">
                    {item.ground_truth_driver
                      ? `Driver: ${item.ground_truth_driver} (${
                          item.significant_drivers?.includes(item.ground_truth_driver)
                            ? "Verified"
                            : "Not in significant list"
                        })`
                      : item.ground_truth_rule}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
