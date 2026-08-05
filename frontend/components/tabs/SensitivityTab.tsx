"use client";

import { useAppSelector, useAppDispatch } from "@/store/hooks";
import { setActiveTab } from "@/store/slices/datasetSlice";
import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
  Sliders,
  TrendingUp,
  ShieldCheck,
  BarChart3,
  Download,
  ArrowRight,
} from "lucide-react";
import { SensitivityMetric, fetchSensitivityMetrics } from "@/lib/api";

const EASE = [0.22, 1, 0.36, 1] as const;

export default function SensitivityTab() {
  const { activeResults, activeDatasetId } = useAppSelector((s) => s.dataset);
  const dispatch = useAppDispatch();
  const [selectedColumn, setSelectedColumn] = useState<string | null>(null);
  const [activeScenario, setActiveScenario] = useState<"mar" | "mcar" | "mnar">("mar");
  const [fetchedMetrics, setFetchedMetrics] = useState<SensitivityMetric[]>([]);

  useEffect(() => {
    if (activeDatasetId && (!activeResults?.sensitivity_metrics || activeResults.sensitivity_metrics.length === 0)) {
      fetchSensitivityMetrics(activeDatasetId)
        .then((data) => setFetchedMetrics(data))
        .catch((err) => console.error("Failed to load sensitivity metrics:", err));
    }
  }, [activeDatasetId, activeResults?.sensitivity_metrics]);

  if (!activeResults || !activeResults.dataset) return null;

  const { sensitivity_metrics = [] } = activeResults;

  // Metrics come from the backend only. There was previously a client-side
  // fallback that synthesised these numbers from hardcoded constants (e.g.
  // stabilityScore = 96, baselineVal = 100 - missingPct * 10) whenever the
  // backend returned nothing. Those values were not derived from the data and
  // were visually indistinguishable from real ones, so a missing CSV on disk
  // silently produced fabricated statistics. If the backend has no metrics we
  // now say so instead of inventing them.
  const metrics: SensitivityMetric[] =
    sensitivity_metrics.length > 0 ? sensitivity_metrics : fetchedMetrics;

  if (metrics.length === 0) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <div className="glass rounded-3xl px-10 py-12 max-w-md text-center">
          <BarChart3 className="w-6 h-6 text-gray-500 mx-auto mb-4" strokeWidth={1.5} />
          <h3 className="text-[17px] font-semibold text-gray-900 mb-2">
            Sensitivity metrics unavailable
          </h3>
          <p className="text-[13px] text-gray-600 leading-relaxed">
            The backend returned no metrics for this dataset. This usually means the
            source CSV could not be read from disk. Re-run the analysis rather than
            treating the absence as a result.
          </p>
        </div>
      </div>
    );
  }

  const activeMetric =
    metrics.find((m) => m.column === selectedColumn) || metrics[0] || null;

  const avgStability = Math.round(
    metrics.reduce((acc, m) => acc + m.stabilityScore, 0) / metrics.length
  );

  const maxShift = Math.max(...metrics.map((m) => m.shiftPct)).toFixed(1);

  const cautionCount = metrics.filter((m) => m.status === "Needs Caution").length;

  return (
    <div className="w-full h-full flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1.8fr_1.2fr] gap-8 overflow-y-auto lg:overflow-hidden">
      {/* Left Column: Stats + Distribution Stability Table */}
      <div className="flex flex-col min-h-0 overflow-hidden pr-2">
        {/* Quick Stats Summary */}
        <div className="grid grid-cols-3 gap-4 mb-7 shrink-0">
          <motion.div
            whileHover={{ y: -2 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="rounded-[24px] border border-white/50 bg-white/90 backdrop-blur-xl px-6 py-5 shadow-[0_4px_12px_rgba(0,0,0,0.04)]"
          >
            <p className="text-sm text-[#6E6E73] mb-2">Mean variance retained</p>
            <div className="flex items-baseline gap-2">
              <p className="text-3xl font-semibold tabular-nums text-[#1D1D1F]">
                {avgStability}%
              </p>
              {/* Derived from the score rather than a fixed "High" label. */}
              <span
                className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                  avgStability >= 95
                    ? "text-[#1F8A3D] bg-[#34C759]/12"
                    : avgStability >= 90
                    ? "text-[#0071E3] bg-[#0071E3]/10"
                    : "text-[#B8791F] bg-[#FFB340]/15"
                }`}
              >
                {avgStability >= 95 ? "High" : avgStability >= 90 ? "Moderate" : "Low"}
              </span>
            </div>
          </motion.div>

          <motion.div
            whileHover={{ y: -2 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="rounded-[24px] border border-white/50 bg-white/90 backdrop-blur-xl px-6 py-5 shadow-[0_4px_12px_rgba(0,0,0,0.04)]"
          >
            <p className="text-sm text-[#6E6E73] mb-2">Max Scenario Shift</p>
            <p className="text-3xl font-semibold tabular-nums text-[#1D1D1F]">
              ±{maxShift}%
            </p>
          </motion.div>

          <motion.div
            whileHover={{ y: -2 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="rounded-[24px] border border-white/50 bg-white/90 backdrop-blur-xl px-6 py-5 shadow-[0_4px_12px_rgba(0,0,0,0.04)]"
          >
            <p className="text-sm text-[#6E6E73] mb-2">Sensitive Columns</p>
            <p
              className={`text-3xl font-semibold tabular-nums ${
                cautionCount > 0 ? "text-[#FFB340]" : "text-[#1D1D1F]"
              }`}
            >
              {cautionCount}
            </p>
          </motion.div>
        </div>

        {/* Section Heading */}
        <div className="shrink-0 mb-5">
          <h3 className="text-xl font-semibold tracking-tight text-[#1D1D1F]">
            Distribution Stability Across Scenarios
          </h3>
          <p className="text-sm text-[#6E6E73] mt-1.5 leading-relaxed">
            Compare how parameter estimates shift between Complete Case baseline, our selected conditional imputation, and extreme worst-case bounds.
          </p>
        </div>

        {/* Column Comparison List */}
        <div className="flex-1 min-h-0 overflow-y-auto pr-2 space-y-3.5">
          {metrics.map((m, idx) => {
            const isSelected = activeMetric?.column === m.column;
            return (
              <motion.div
                key={m.column}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, ease: EASE, delay: Math.min(idx * 0.03, 0.3) }}
                onClick={() => setSelectedColumn(m.column)}
                className={`cursor-pointer rounded-[24px] border p-5 transition-all duration-200 ${
                  isSelected
                    ? "bg-white border-[#0071E3]/40 shadow-[0_6px_20px_rgba(0,113,227,0.08)] ring-1 ring-[#0071E3]/30"
                    : "bg-white/80 border-white/60 hover:bg-white shadow-[0_2px_8px_rgba(0,0,0,0.03)]"
                }`}
              >
                <div className="flex items-center justify-between gap-3 mb-3.5">
                  <div className="flex items-center gap-2.5">
                    <code className="text-base font-mono font-semibold text-[#1D1D1F]">
                      {m.column}
                    </code>
                    <span className="text-xs font-medium text-[#8E8E93] bg-[#F5F5F7] px-2.5 py-1 rounded-full uppercase tracking-wider">
                      {m.type}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {m.status === "Highly Stable" && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#34C759]/12 px-2.5 py-1 text-xs font-medium text-[#1F8A3D]">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        {m.status}
                      </span>
                    )}
                    {m.status === "Robust" && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#0071E3]/10 px-2.5 py-1 text-xs font-medium text-[#0071E3]">
                        <ShieldCheck className="w-3.5 h-3.5" />
                        {m.status}
                      </span>
                    )}
                    {m.status === "Needs Caution" && (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-[#FFB340]/15 px-2.5 py-1 text-xs font-medium text-[#B8791F]">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        {m.status}
                      </span>
                    )}
                    {m.status === "Not Imputed (Identifier)" && (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-[#F5F5F7] px-2.5 py-1 text-xs font-medium text-[#6E6E73]">
                        {m.status}
                      </span>
                    )}
                  </div>
                </div>

                {/* Comparison Bar / Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 pb-1 text-xs">
                  <div className="bg-[#F5F5F7]/80 rounded-xl p-3">
                    <span className="text-[#8E8E93] block mb-1 font-medium">Complete Case</span>
                    <span className="font-mono font-medium text-[#3A3A3C]">{m.baselineVal}</span>
                  </div>
                  <div className="bg-[#0071E3]/8 border border-[#0071E3]/15 rounded-xl p-3">
                    <span className="text-[#0071E3] block mb-1 font-semibold">Selected Strategy</span>
                    <span className="font-mono font-semibold text-[#1D1D1F]">{m.primaryVal}</span>
                  </div>
                  <div className="bg-[#F5F5F7]/80 rounded-xl p-3">
                    <span className="text-[#8E8E93] block mb-1 font-medium">Worst-Case Bound</span>
                    <span className="font-mono font-medium text-[#6E6E73]">{m.worstCaseVal}</span>
                  </div>
                </div>

                <p className="text-xs text-[#6E6E73] mt-3 leading-relaxed">
                  {m.description}
                </p>
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* Right Column: Scenario Exploration & Action Card */}
      <div className="flex flex-col min-h-0 rounded-[28px] border border-white/50 bg-white/90 backdrop-blur-xl shadow-[0_8px_30px_rgba(0,0,0,0.06)] px-6 py-6">
        <div className="shrink-0 mb-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xl font-semibold tracking-tight text-[#1D1D1F]">
              Scenario Exploration
            </h3>
            <Sliders className="w-5 h-5 text-[#AEAEB2]" strokeWidth={1.75} />
          </div>
          <p className="text-sm text-[#6E6E73] mt-1.5 leading-relaxed">
            Examine how {activeMetric?.column ? <code className="font-mono font-medium text-[#1D1D1F]">{activeMetric.column}</code> : "selected column"} behaves across theoretical missingness assumptions.
          </p>
        </div>

        {activeMetric ? (
          <div className="flex-1 min-h-0 overflow-y-auto pr-1 -mx-1 space-y-4">
            {/* Scenario Toggles */}
            <div className="flex bg-[#F5F5F7] p-1 rounded-2xl gap-1">
              {(["mar", "mcar", "mnar"] as const).map((scen) => (
                <button
                  key={scen}
                  type="button"
                  onClick={() => setActiveScenario(scen)}
                  className={`flex-1 py-2 px-3 rounded-xl text-xs font-semibold uppercase tracking-wider transition-all ${
                    activeScenario === scen
                      ? "bg-white text-[#1D1D1F] shadow-sm"
                      : "text-[#8E8E93] hover:text-[#3A3A3C]"
                  }`}
                >
                  {scen.toUpperCase()}
                </button>
              ))}
            </div>

            {/* Active Scenario Detail Card */}
            <AnimatePresence mode="wait">
              <motion.div
                key={activeScenario}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.2, ease: EASE }}
                className="rounded-2xl bg-[#F5F5F7]/80 p-5 space-y-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[#8E8E93]">
                    {activeScenario === "mar"
                      ? "Missing At Random (Primary Assumption)"
                      : activeScenario === "mcar"
                      ? "Missing Completely At Random"
                      : "Missing Not At Random (Extreme Bound)"}
                  </span>
                  {/* The score is a property of the imputed column, not of the
                      scenario being viewed. It previously had +4 added under
                      MCAR and 15 subtracted under MNAR, which invented three
                      different numbers from one measurement. */}
                  <span className="font-mono text-xs font-bold text-[#0071E3]">
                    Variance retained: {activeMetric.stabilityScore}%
                  </span>
                </div>
                <p className="text-sm text-[#3A3A3C] leading-relaxed">
                  {activeMetric.scenarioNotes[activeScenario]}
                </p>
              </motion.div>
            </AnimatePresence>

            {/* Subgroup Impact Breakdown */}
            <div className="rounded-2xl border border-[#E5E5E7] p-5 space-y-3">
              <h4 className="text-sm font-semibold text-[#1D1D1F] flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-[#0071E3]" />
                Distribution impact
              </h4>
              {/* The previous copy claimed a bound on downstream regression
                  coefficients. Nothing here measures that: the figure is the
                  shift in this column's own mean. */}
              <p className="text-xs text-[#6E6E73] leading-relaxed">
                Imputing <code className="font-mono font-medium text-[#1D1D1F]">{activeMetric.column}</code> retains{" "}
                <strong className="text-[#1D1D1F]">{activeMetric.stabilityScore}%</strong> of its original spread and moves its
                mean by <strong className="text-[#1D1D1F]">{activeMetric.shiftPct}%</strong>. This describes the column itself,
                not the effect on any downstream model.
              </p>
              <div className="w-full bg-[#E8E8ED] h-2 rounded-full overflow-hidden mt-2">
                <div
                  className="bg-[#0071E3] h-full rounded-full transition-all duration-500"
                  style={{ width: `${activeMetric.stabilityScore}%` }}
                />
              </div>
              <div className="flex justify-between text-[11px] text-[#8E8E93]">
                <span>Spread collapsed (0%)</span>
                <span>Spread preserved ({activeMetric.stabilityScore}%)</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-[#8E8E93]">
            Select a column on the left to view scenario breakdown.
          </div>
        )}

        {/* Bottom Actions */}
        <div className="shrink-0 pt-5 mt-auto space-y-2.5">
          <motion.button
            type="button"
            whileHover={{ scale: 1.01 }}
            whileTap={{ scale: 0.99 }}
            transition={{ duration: 0.2, ease: EASE }}
            onClick={() => dispatch(setActiveTab("diagnosis"))}
            className="inline-flex items-center justify-center gap-2.5 bg-[#0071E3] hover:bg-[#0077ED] text-white text-base font-medium px-6 py-3.5 rounded-full shadow-[0_4px_12px_rgba(0,113,227,0.25)] hover:shadow-[0_6px_16px_rgba(0,113,227,0.32)] transition-shadow duration-300 w-full"
          >
            Review Diagnostic Rationale →
          </motion.button>

          <motion.button
            type="button"
            whileHover={{ scale: 1.01 }}
            whileTap={{ scale: 0.99 }}
            transition={{ duration: 0.2, ease: EASE }}
            onClick={() => dispatch(setActiveTab("explanation"))}
            className="inline-flex items-center justify-center gap-2 bg-[#F5F5F7] hover:bg-[#E8E8ED] text-[#1D1D1F] text-sm font-medium px-6 py-3 rounded-full transition-colors duration-200 w-full"
          >
            View Plain-Language Explanations
          </motion.button>
        </div>
      </div>
    </div>
  );
}
