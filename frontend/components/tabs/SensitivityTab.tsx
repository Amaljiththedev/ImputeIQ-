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
import {
  SensitivityMetric,
  RobustnessColumn,
  fetchSensitivityMetrics,
  fetchRobustness,
} from "@/lib/api";

const EASE = [0.22, 1, 0.36, 1] as const;

export default function SensitivityTab() {
  const { activeResults, activeDatasetId } = useAppSelector((s) => s.dataset);
  const dispatch = useAppDispatch();
  const [selectedColumn, setSelectedColumn] = useState<string | null>(null);
  const [activeScenario, setActiveScenario] = useState<"mar" | "mcar" | "mnar">("mar");
  const [fetchedMetrics, setFetchedMetrics] = useState<SensitivityMetric[]>([]);
  const [robustness, setRobustness] = useState<RobustnessColumn[]>([]);

  useEffect(() => {
    if (activeDatasetId && (!activeResults?.sensitivity_metrics || activeResults.sensitivity_metrics.length === 0)) {
      fetchSensitivityMetrics(activeDatasetId)
        .then((data) => setFetchedMetrics(data))
        .catch((err) => console.error("Failed to load sensitivity metrics:", err));
    }
  }, [activeDatasetId, activeResults?.sensitivity_metrics]);

  useEffect(() => {
    if (!activeDatasetId) return;
    let live = true;
    fetchRobustness(activeDatasetId)
      .then((r) => { if (live) setRobustness(r.columns || []); })
      .catch(() => { if (live) setRobustness([]); });
    return () => { live = false; };
  }, [activeDatasetId]);

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

  // Open on a column the robustness comparison actually covers. Falling back to
  // metrics[0] put an identifier (never imputed, so never analysed) in the panel
  // on first render, which silently hid the robustness block until the user
  // happened to click a numeric column.
  const defaultMetric =
    metrics.find((m) => robustness.some((r) => r.column === m.column)) ||
    metrics[0] ||
    null;

  const activeMetric =
    metrics.find((m) => m.column === selectedColumn) || defaultMetric;

  const avgStability = Math.round(
    metrics.reduce((acc, m) => acc + m.stabilityScore, 0) / metrics.length
  );

  const maxShift = Math.max(...metrics.map((m) => m.shiftPct)).toFixed(1);

  const cautionCount = metrics.filter((m) => m.status === "Needs Caution").length;

  const activeRobustness = activeMetric
    ? robustness.find((r) => r.column === activeMetric.column) ?? null
    : null;

  return (
    <div className="w-full h-full flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1.8fr_1.2fr] gap-8 overflow-y-auto lg:overflow-hidden">
      {/* Left Column: Stats + Distribution Stability Table */}
      <div className="flex flex-col min-h-0 overflow-hidden pr-2">
        {/* Quick Stats Summary */}
        <div className="grid grid-cols-3 gap-4 mb-7 shrink-0">
          <motion.div
            whileHover={{ y: -2 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="glass rounded-2xl px-6 py-5"
          >
            <p className="text-sm text-gray-600 mb-2">Mean variance retained</p>
            <div className="flex items-baseline gap-2">
              <p className="text-3xl font-semibold tabular-nums text-gray-900">
                {avgStability}%
              </p>
              {/* Derived from the score rather than a fixed "High" label. */}
              <span
                className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                  avgStability >= 95
                    ? "text-success-fg bg-success/12"
                    : avgStability >= 90
                    ? "text-blue-500 bg-blue-500/10"
                    : "text-warning-fg bg-warning/15"
                }`}
              >
                {avgStability >= 95 ? "High" : avgStability >= 90 ? "Moderate" : "Low"}
              </span>
            </div>
          </motion.div>

          <motion.div
            whileHover={{ y: -2 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="glass rounded-2xl px-6 py-5"
          >
            <p className="text-sm text-gray-600 mb-2">Max Scenario Shift</p>
            <p className="text-3xl font-semibold tabular-nums text-gray-900">
              ±{maxShift}%
            </p>
          </motion.div>

          <motion.div
            whileHover={{ y: -2 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="glass rounded-2xl px-6 py-5"
          >
            <p className="text-sm text-gray-600 mb-2">Sensitive Columns</p>
            <p
              className={`text-3xl font-semibold tabular-nums ${
                cautionCount > 0 ? "text-warning" : "text-gray-900"
              }`}
            >
              {cautionCount}
            </p>
          </motion.div>
        </div>

        {/* Section Heading */}
        <div className="shrink-0 mb-5">
          <h3 className="text-xl font-semibold tracking-tight text-gray-900">
            Distribution Stability Across Scenarios
          </h3>
          <p className="text-sm text-gray-600 mt-1.5 leading-relaxed">
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
                className={`cursor-pointer rounded-2xl border p-5 transition-all duration-200 ${
                  isSelected
                    ? "bg-white border-blue-500/40 shadow-[0_6px_20px_rgba(0,113,227,0.08)] ring-1 ring-blue-500/30"
                    : "bg-white/80 border-white/60 hover:bg-white shadow-[0_2px_8px_rgba(0,0,0,0.03)]"
                }`}
              >
                <div className="flex items-center justify-between gap-3 mb-3.5">
                  <div className="flex items-center gap-2.5">
                    <code className="text-base font-mono font-semibold text-gray-900">
                      {m.column}
                    </code>
                    <span className="text-xs font-medium text-gray-500 bg-gray-100 px-2.5 py-1 rounded-full uppercase tracking-wider">
                      {m.type}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {m.status === "Highly Stable" && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-success/12 px-2.5 py-1 text-xs font-medium text-success-fg">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        {m.status}
                      </span>
                    )}
                    {m.status === "Robust" && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-blue-500/10 px-2.5 py-1 text-xs font-medium text-blue-500">
                        <ShieldCheck className="w-3.5 h-3.5" />
                        {m.status}
                      </span>
                    )}
                    {m.status === "Needs Caution" && (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-warning/15 px-2.5 py-1 text-xs font-medium text-warning-fg">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        {m.status}
                      </span>
                    )}
                    {m.status === "Not Imputed (Identifier)" && (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">
                        {m.status}
                      </span>
                    )}
                  </div>
                </div>

                {/* Comparison Bar / Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 pb-1 text-xs">
                  <div className="bg-gray-100/80 rounded-xl p-3">
                    <span className="text-gray-500 block mb-1 font-medium">Complete Case</span>
                    <span className="font-mono font-medium text-gray-700">{m.baselineVal}</span>
                  </div>
                  <div className="bg-blue-500/8 border border-blue-500/15 rounded-xl p-3">
                    <span className="text-blue-500 block mb-1 font-semibold">Selected Strategy</span>
                    <span className="font-mono font-semibold text-gray-900">{m.primaryVal}</span>
                  </div>
                  <div className="bg-gray-100/80 rounded-xl p-3">
                    <span className="text-gray-500 block mb-1 font-medium">Worst-Case Bound</span>
                    <span className="font-mono font-medium text-gray-600">{m.worstCaseVal}</span>
                  </div>
                </div>

                <p className="text-xs text-gray-600 mt-3 leading-relaxed">
                  {m.description}
                </p>
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* Right Column: Scenario Exploration & Action Card */}
      <div className="flex flex-col min-h-0 glass rounded-3xl px-6 py-6">
        <div className="shrink-0 mb-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xl font-semibold tracking-tight text-gray-900">
              Scenario Exploration
            </h3>
            <Sliders className="w-5 h-5 text-gray-400" strokeWidth={1.75} />
          </div>
          <p className="text-sm text-gray-600 mt-1.5 leading-relaxed">
            Examine how {activeMetric?.column ? <code className="font-mono font-medium text-gray-900">{activeMetric.column}</code> : "selected column"} behaves across theoretical missingness assumptions.
          </p>
        </div>

        {activeMetric ? (
          <div className="flex-1 min-h-0 overflow-y-auto pr-1 -mx-1 space-y-4">
            {/* Scenario Toggles */}
            <div className="flex bg-gray-100 p-1 rounded-2xl gap-1">
              {(["mar", "mcar", "mnar"] as const).map((scen) => (
                <button
                  key={scen}
                  type="button"
                  onClick={() => setActiveScenario(scen)}
                  className={`flex-1 py-2 px-3 rounded-xl text-xs font-semibold uppercase tracking-wider transition-all ${
                    activeScenario === scen
                      ? "bg-white text-gray-900 shadow-sm"
                      : "text-gray-500 hover:text-gray-700"
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
                className="rounded-2xl bg-gray-100/80 p-5 space-y-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">
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
                  <span className="font-mono text-xs font-bold text-blue-500">
                    Variance retained: {activeMetric.stabilityScore}%
                  </span>
                </div>
                <p className="text-sm text-gray-700 leading-relaxed">
                  {activeMetric.scenarioNotes[activeScenario]}
                </p>
              </motion.div>
            </AnimatePresence>

            {/* Subgroup Impact Breakdown */}
            <div className="rounded-2xl border border-gray-200 p-5 space-y-3">
              <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-blue-500" />
                Distribution impact
              </h4>
              {/* The previous copy claimed a bound on downstream regression
                  coefficients. Nothing here measures that: the figure is the
                  shift in this column's own mean. */}
              <p className="text-xs text-gray-600 leading-relaxed">
                Imputing <code className="font-mono font-medium text-gray-900">{activeMetric.column}</code> retains{" "}
                <strong className="text-gray-900">{activeMetric.stabilityScore}%</strong> of its original spread and moves its
                mean by <strong className="text-gray-900">{activeMetric.shiftPct}%</strong>. This describes the column itself,
                not the effect on any downstream model.
              </p>
              <div className="w-full bg-gray-200 h-2 rounded-full overflow-hidden mt-2">
                <div
                  className="bg-blue-500 h-full rounded-full transition-all duration-500"
                  style={{ width: `${activeMetric.stabilityScore}%` }}
                />
              </div>
              <div className="flex justify-between text-[11px] text-gray-500">
                <span>Spread collapsed (0%)</span>
                <span>Spread preserved ({activeMetric.stabilityScore}%)</span>
              </div>
            </div>

            {/* Robustness. The block above describes what imputation did to this
                column. This one asks the different, and more consequential,
                question: would a result derived from it survive a different
                imputation choice, or a different assumption about the values
                that were never recorded? It needs no ground truth. */}
            {!activeRobustness ? (
              <div className="rounded-2xl border border-gray-200 p-5">
                <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                  <Sliders className="w-4 h-4 text-gray-400" />
                  Would the result change?
                </h4>
                {/* Say why rather than rendering nothing. An empty space reads as
                    "no problem found", which is a different claim from "not
                    measured". */}
                <p className="text-xs text-gray-600 leading-relaxed mt-1">
                  Not computed for{" "}
                  <code className="font-mono font-medium text-gray-900">{activeMetric.column}</code>.
                  The comparison re-estimates the column mean under several imputation
                  strategies, so it applies only to numeric columns that were imputed.
                  Identifiers and columns left flagged are excluded.
                </p>
              </div>
            ) : (
              <div className="rounded-2xl border border-gray-200 p-5 space-y-4">
                <div>
                  <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                    <Sliders className="w-4 h-4 text-blue-500" />
                    Would the result change?
                  </h4>
                  <p className="text-xs text-gray-600 leading-relaxed mt-1">
                    {activeRobustness.interpretation}
                  </p>
                </div>

                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-gray-400 mb-2">
                    Estimate under each strategy
                  </p>
                  {/* Validity matters more than the numbers here. Mean, median
                      and complete-case are unbiased only under MCAR
                      (van Buuren 2018, Table 1.1), so for a MAR column they
                      differ by construction. Showing them as equals would
                      report disagreement that is expected rather than
                      informative, so they are marked and excluded from the
                      spread. */}
                  <div className="space-y-1">
                    {activeRobustness.strategies.map((s) => {
                      const valid = s.valid_under_mechanism === true;
                      return (
                        <div key={s.strategy} className="flex items-center justify-between text-xs gap-3">
                          <span className="flex items-center gap-2 min-w-0">
                            <span className={`font-mono truncate ${valid ? "text-gray-900" : "text-gray-400"}`}>
                              {s.strategy === "complete_case" ? "complete case" : s.strategy}
                            </span>
                            {!valid && (
                              <span
                                title="Unbiased only under MCAR, so not valid for this column's diagnosed mechanism"
                                className="shrink-0 rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500"
                              >
                                not valid here
                              </span>
                            )}
                          </span>
                          <span className={`tabular-nums shrink-0 ${valid ? "text-gray-900" : "text-gray-400"}`}>
                            {s.estimate.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                            {typeof s.shift_vs_complete_case_pct === "number" && s.strategy !== "complete_case" && (
                              <span className="ml-2 text-gray-500">
                                {s.shift_vs_complete_case_pct > 0 ? "+" : ""}
                                {s.shift_vs_complete_case_pct}%
                              </span>
                            )}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  <p className="text-[11px] text-gray-500 mt-2 leading-relaxed">
                    {activeRobustness.valid_methods && activeRobustness.valid_methods.length > 0 ? (
                      <>
                        Spread of <strong className="text-gray-900">{activeRobustness.spread_pct_of_estimate}%</strong>{" "}
                        measured across {activeRobustness.valid_methods.join(" and ")}, the methods unbiased under
                        this mechanism. Greyed rows are shown for contrast only.
                      </>
                    ) : (
                      <>No method is unbiased under this mechanism, so the comparison is descriptive only.</>
                    )}
                  </p>
                </div>

                {activeRobustness.mnar_sweep.length > 0 && (
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-gray-400 mb-2">
                      If the unrecorded values were different
                    </p>
                    <div className="flex items-end gap-1.5 h-16">
                      {activeRobustness.mnar_sweep.map((p) => {
                        const values = activeRobustness.mnar_sweep.map((q) => q.estimate);
                        const lo = Math.min(...values);
                        const hi = Math.max(...values);
                        const height = hi === lo ? 50 : 20 + ((p.estimate - lo) / (hi - lo)) * 80;
                        return (
                          <div key={p.delta_sd} className="flex-1 flex flex-col items-center gap-1">
                            <div
                              title={`${p.assumption}: ${p.estimate}`}
                              className={`w-full rounded-t ${p.delta_sd === 0 ? "bg-blue-500" : "bg-blue-500/25"}`}
                              style={{ height: `${height}%` }}
                            />
                            <span className="text-[10px] text-gray-500 tabular-nums">
                              {p.delta_sd > 0 ? "+" : ""}
                              {p.delta_sd}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                    <p className="text-[11px] text-gray-500 mt-2 leading-relaxed">
                      Standard deviations of assumed departure. The solid bar is the assumption
                      actually used. A conclusion that holds across the whole range does not
                      depend on it.
                      {/* The shift applies only to imputed cells, so its effect on the
                          mean scales with how much is missing. Stating both keeps the
                          figure comparable with other columns. */}
                      {typeof activeRobustness.missing_fraction === "number" && (
                        <>
                          {" "}This column is{" "}
                          <strong className="text-gray-900">
                            {(activeRobustness.missing_fraction * 100).toFixed(1)}%
                          </strong>{" "}
                          missing, and the shift applies only to those rows, so its effect on the
                          mean scales with that proportion.
                        </>
                      )}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-gray-500">
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
            className="inline-flex items-center justify-center gap-2.5 bg-blue-500 hover:bg-blue-600 text-white text-base font-medium px-6 py-3.5 rounded-full shadow-[0_4px_12px_rgba(0,113,227,0.25)] hover:shadow-[0_6px_16px_rgba(0,113,227,0.32)] transition-shadow duration-300 w-full"
          >
            Review Diagnostic Rationale →
          </motion.button>

          <motion.button
            type="button"
            whileHover={{ scale: 1.01 }}
            whileTap={{ scale: 0.99 }}
            transition={{ duration: 0.2, ease: EASE }}
            onClick={() => dispatch(setActiveTab("explanation"))}
            className="inline-flex items-center justify-center gap-2 bg-gray-100 hover:bg-gray-200 text-gray-900 text-sm font-medium px-6 py-3 rounded-full transition-colors duration-200 w-full"
          >
            View Plain-Language Explanations
          </motion.button>
        </div>
      </div>
    </div>
  );
}
