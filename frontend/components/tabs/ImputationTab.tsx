"use client";

import { useAppSelector, useAppDispatch } from "@/store/hooks";
import { useState } from "react";
import { Download, AlertTriangle, CheckCircle2, HelpCircle, Sparkles, RotateCcw } from "lucide-react";
import { downloadCleanedCsv, approveImputation, getJobStatus } from "@/lib/api";
import { fetchResults } from "@/store/slices/datasetSlice";
import { motion } from "framer-motion";

// Offered when re-running a column. Restricted to methods that make sense for
// a continuous variable: mode is for lookup codes and flag_only for
// identifiers, and neither is reachable from a column the router sent here.
const RERUN_METHODS = ["pmm", "mice", "knn", "median", "mean", "regression"];

const EASE = [0.22, 1, 0.36, 1] as const;

function isFlagOnly(method?: string | null): boolean {
  if (!method) return false;
  const lower = method.trim().toLowerCase().replace(/[- ]/g, "_");
  return lower === "flag_only";
}

function formatMethodName(method: string): string {
  if (method === "not_implemented") return "Not yet supported";
  const lower = method.trim().toLowerCase().replace(/[- ]/g, "_");
  if (lower === "pmm") return "PMM";
  if (lower === "mice") return "MICE";
  if (lower === "knn") return "KNN";
  if (lower === "mean") return "Mean";
  if (lower === "median") return "Median";
  if (lower === "mode") return "Mode (Most Frequent)";
  if (lower === "flag_only") return "Flag Only (<col>_missing indicator)";
  if (lower === "zero") return "Structural Zero Fill";
  if (lower === "regression") return "Regression";
  return method.charAt(0).toUpperCase() + method.slice(1);
}

function formatSemanticRole(role?: string | null) {
  if (!role) return null;
  const lower = role.toLowerCase();
  if (lower === "identifier") return "Key/ID";
  if (lower === "categorical") return "Categorical";
  if (lower === "continuous") return "Continuous";
  return role;
}

export default function ImputationTab() {
  const { activeResults, activeDatasetId } = useAppSelector((s) => s.dataset);
  const dispatch = useAppDispatch();
  const [downloading, setDownloading] = useState(false);
  // Pending method changes, per column, not yet applied.
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [rerunning, setRerunning] = useState(false);
  const [rerunError, setRerunError] = useState<string | null>(null);

  if (!activeResults) return null;
  const { imputation_results = [], dataset } = activeResults;

  const targetId = activeDatasetId || dataset?.id;
  const pendingCount = Object.keys(overrides).length;

  /** Re-impute the changed columns and refresh the results in place.
   *  The imputation itself is cheap to repeat, and a routed method is a
   *  recommendation rather than a verdict -- an analyst who disagrees with it
   *  should be able to say so after seeing the result, not only before. */
  const handleRerun = async () => {
    if (!targetId || pendingCount === 0) return;
    setRerunning(true);
    setRerunError(null);
    try {
      const job = await approveImputation(targetId, overrides);
      // Poll rather than assume: imputation and the explanation that follows
      // run in the background, and refreshing early shows the previous run.
      for (let i = 0; i < 90; i++) {
        const status = await getJobStatus(job.id);
        if (status.status === "complete" || status.status === "completed") break;
        if (status.status === "failed") {
          throw new Error(status.error_message || "Re-run failed");
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
      await dispatch(fetchResults(targetId));
      setOverrides({});
    } catch (err) {
      setRerunError(err instanceof Error ? err.message : "Re-run failed");
    } finally {
      setRerunning(false);
    }
  };

  const handleDownload = async () => {
    const targetId = activeDatasetId || dataset?.id;
    if (!targetId) return;
    try {
      setDownloading(true);
      const filename = dataset?.filename ? `cleaned_${dataset.filename}` : "cleaned_dataset.csv";
      await downloadCleanedCsv(targetId, filename);
    } catch (err) {
      console.error("Download failed:", err);
    } finally {
      setDownloading(false);
    }
  };

  // 0. Empty state
  if (imputation_results.length === 0) {
    return (
      <div className="space-y-8 pb-12">
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE }}
        >
          <h1 className="text-3xl font-semibold text-gray-900 tracking-tight">
            Imputation
          </h1>
          <p className="text-sm text-gray-600 mt-1.5">
            How missing values were filled in, and why.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE, delay: 0.05 }}
          className="glass rounded-3xl px-10 py-16 text-center"
        >
          <div className="w-12 h-12 rounded-2xl bg-gray-100 flex items-center justify-center mx-auto mb-4">
            <HelpCircle className="w-5 h-5 text-gray-400" strokeWidth={1.5} />
          </div>
          <p className="text-sm text-gray-600">
            Imputation hasn&apos;t been run yet.
          </p>
        </motion.div>
      </div>
    );
  }

  const isFlagOrId = (imp: typeof imputation_results[number]) =>
    isFlagOnly(imp.method_used) || imp.semantic_role?.toLowerCase() === "identifier";

  const notImplementedCols = imputation_results.filter(
    (imp) => imp.method_used === "not_implemented"
  );
  const flaggedCols = imputation_results.filter((imp) => isFlagOrId(imp));
  const lowConfidenceCols = imputation_results.filter(
    (imp) => imp.low_confidence && imp.method_used !== "not_implemented" && !isFlagOrId(imp)
  );
  const resolvedCols = imputation_results.filter(
    (imp) => !imp.low_confidence && imp.method_used !== "not_implemented" && !isFlagOrId(imp)
  );
  const allHavePaths = imputation_results.every((imp) => Boolean(imp.imputed_file_path));
  const canDownloadAll = allHavePaths && notImplementedCols.length === 0;

  // Surface columns that need attention first: unsupported, then low
  // confidence, then everything else -- same principle as the Diagnosis tab.
  const sortedImputations = [...imputation_results].sort((a, b) => {
    const rank = (imp: typeof a) =>
      imp.method_used === "not_implemented" ? 0 : imp.low_confidence && !isFlagOrId(imp) ? 1 : isFlagOrId(imp) ? 2 : 3;
    return rank(a) - rank(b);
  });

  const totalValuesFilled = imputation_results.reduce(
    (sum, imp) => (isFlagOnly(imp.method_used) ? sum : sum + (imp.n_imputed || 0)),
    0
  );
  const totalFlaggedLeftNull = imputation_results.reduce(
    (sum, imp) => (isFlagOnly(imp.method_used) ? sum + (imp.n_imputed || 0) : sum),
    0
  );

  return (
    <div className="space-y-8 pb-12">
      {/* 1. Page heading */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: EASE }}
      >
        <h1 className="text-3xl font-semibold text-gray-900 tracking-tight">
          Imputation
        </h1>
        <p className="text-sm text-gray-600 mt-1.5">
          How missing values were filled in, and why.
        </p>
      </motion.div>

      {/* 2. Quick stats -- same card language as Overview, orienting the
          user before the detail below. */}
      <div
        className={`grid grid-cols-2 ${
          totalFlaggedLeftNull > 0 ? "sm:grid-cols-4" : "sm:grid-cols-3"
        } gap-4`}
      >
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE, delay: 0.03 }}
          whileHover={{ y: -2 }}
          className="glass rounded-2xl px-6 py-5"
        >
          <p className="text-sm text-gray-600 mb-2">Values filled in</p>
          <p className="text-3xl font-semibold tabular-nums text-gray-900">
            {totalValuesFilled.toLocaleString()}
          </p>
        </motion.div>
        {(totalFlaggedLeftNull > 0 || flaggedCols.length > 0) && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: EASE, delay: 0.045 }}
            whileHover={{ y: -2 }}
            className="glass rounded-2xl px-6 py-5"
          >
            <p className="text-sm text-gray-600 mb-2">Structural / Flagged</p>
            <p className="text-3xl font-semibold tabular-nums text-blue-500">
              {totalFlaggedLeftNull.toLocaleString()}
            </p>
          </motion.div>
        )}
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE, delay: 0.06 }}
          whileHover={{ y: -2 }}
          className="glass rounded-2xl px-6 py-5"
        >
          <p className="text-sm text-gray-600 mb-2">Resolved confidently</p>
          <p className="text-3xl font-semibold tabular-nums text-gray-900">
            {resolvedCols.length.toLocaleString()}
          </p>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE, delay: 0.09 }}
          whileHover={{ y: -2 }}
          className="glass rounded-2xl px-6 py-5"
        >
          <p className="text-sm text-gray-600 mb-2">Ambiguous, needs review</p>
          <p className="text-3xl font-semibold tabular-nums text-warning">
            {(lowConfidenceCols.length + notImplementedCols.length).toLocaleString()}
          </p>
        </motion.div>
      </div>

      {/* 3. Download / status banner */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: EASE, delay: 0.1 }}
        className={`glass rounded-3xl px-7 py-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-5 ${
          notImplementedCols.length > 0
            ? "bg-warning/8 border border-warning/25"
            : "bg-white/90 border border-white/50"
        }`}
      >
        <div className="flex items-start gap-3.5">
          <div
            className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
              notImplementedCols.length > 0 ? "bg-warning/15" : "bg-success/12"
            }`}
          >
            {notImplementedCols.length > 0 ? (
              <AlertTriangle className="w-4.5 h-4.5 text-warning-fg" strokeWidth={1.75} />
            ) : (
              <CheckCircle2 className="w-4.5 h-4.5 text-success-fg" strokeWidth={1.75} />
            )}
          </div>
          <div>
            <h2 className="text-lg font-medium text-gray-900">
              {canDownloadAll ? "Cleaned dataset ready" : "Partial imputation completed"}
            </h2>
            <p className="text-sm text-gray-600 mt-1 leading-relaxed max-w-xl">
              {canDownloadAll ? (
                "All affected columns have been filled in and merged into your cleaned dataset."
              ) : notImplementedCols.length > 0 ? (
                <>
                  {notImplementedCols.length} column{notImplementedCols.length > 1 ? "s" : ""} with
                  text categories couldn&apos;t be automatically filled in yet — the download will
                  still include the remaining gaps in{" "}
                  <span className="font-medium text-warning-fg">
                    {notImplementedCols.map((c) => c.target_column).join(", ")}
                  </span>
                  .
                </>
              ) : (
                "Download your imputed dataset with missing values filled according to your strategy."
              )}
            </p>
          </div>
        </div>
        <motion.button
          type="button"
          whileHover={{ scale: 1.01 }}
          whileTap={{ scale: 0.99 }}
          transition={{ duration: 0.2, ease: EASE }}
          onClick={handleDownload}
          disabled={downloading}
          className="inline-flex items-center justify-center gap-2.5 bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium px-6 py-3 rounded-full shadow-[0_4px_12px_rgba(0,113,227,0.25)] hover:shadow-[0_6px_16px_rgba(0,113,227,0.32)] transition-shadow duration-300 shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Download className="w-4 h-4" />
          {downloading ? "Downloading…" : "Download cleaned CSV"}
        </motion.button>
      </motion.div>

      {/* 4. Per-column method cards -- columns needing attention surface
          first, mirroring the Diagnosis tab's hierarchy. */}
      <div className="space-y-4">
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE, delay: 0.12 }}
        >
          <h2 className="text-xl font-semibold tracking-tight text-gray-900">
            Applied methods &amp; rationale
          </h2>
          <p className="text-sm text-gray-600 mt-1">
            Columns needing a closer look are listed first.
          </p>
        </motion.div>

        {(pendingCount > 0 || rerunning || rerunError) && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-blue-500/30 bg-blue-500/[0.06] px-5 py-3.5"
          >
            <div className="text-sm text-gray-700">
              {rerunError ? (
                <span className="text-warning-fg">{rerunError}</span>
              ) : rerunning ? (
                "Re-running imputation and regenerating the explanation…"
              ) : (
                <>
                  <strong className="text-gray-900">
                    {pendingCount} column{pendingCount === 1 ? "" : "s"}
                  </strong>{" "}
                  changed. The data is re-imputed from the original values, so this replaces the
                  previous result rather than stacking on it.
                </>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => { setOverrides({}); setRerunError(null); }}
                disabled={rerunning}
                className="rounded-full px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-900 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRerun}
                disabled={rerunning || pendingCount === 0}
                className="inline-flex items-center gap-2 rounded-full bg-blue-500 px-5 py-2 text-sm font-medium text-white shadow-[0_4px_12px_rgba(0,113,227,0.25)] hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <RotateCcw className={`w-3.5 h-3.5 ${rerunning ? "animate-spin" : ""}`} />
                {rerunning ? "Re-running…" : "Re-run imputation"}
              </button>
            </div>
          </motion.div>
        )}

        <div className="space-y-3">
          {sortedImputations.map((imp, idx) => {
            const isFlag = isFlagOrId(imp);
            const isNotImplemented = imp.method_used === "not_implemented";
            const isLowConfidence = imp.low_confidence && !isNotImplemented && !isFlag;

            return (
              <motion.div
                key={imp.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, ease: EASE, delay: Math.min(idx * 0.03, 0.3) }}
                className={`rounded-3xl border glass px-6 py-5 space-y-3.5 ${
                  isNotImplemented
                    ? "border-gray-400/30"
                    : isLowConfidence
                    ? "border-warning/25"
                    : isFlag
                    ? "border-blue-500/25"
                    : "border-white/50"
                }`}
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3.5 border-b border-gray-100">
                  <div className="flex items-center flex-wrap gap-2.5">
                    <span className="font-mono font-medium text-base text-gray-900 bg-gray-100 px-3 py-1.5 rounded-full">
                      {imp.target_column}
                    </span>
                    {imp.semantic_role && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-blue-500/10 px-2.5 py-1 text-xs font-medium text-blue-500">
                        {formatSemanticRole(imp.semantic_role)}
                      </span>
                    )}
                    <span className="text-xs font-medium text-gray-500 tabular-nums">
                      {isFlagOnly(imp.method_used)
                        ? `${imp.n_imputed.toLocaleString()} flagged, left null`
                        : `${imp.n_imputed.toLocaleString()} values filled in`}
                    </span>
                    {/* A download with gaps the report does not account for is
                        worse than one with gaps it explains. */}
                    {!isFlagOnly(imp.method_used) && (imp.n_unimputable ?? 0) > 0 && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-warning/12 px-2.5 py-1 text-xs font-medium text-warning-fg tabular-nums">
                        <AlertTriangle className="w-3 h-3 shrink-0" />
                        {imp.n_unimputable!.toLocaleString()} left missing
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2 shrink-0 self-start sm:self-auto">
                    {isNotImplemented ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">
                        Not yet supported
                      </span>
                    ) : isFlag ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-500/12 px-2.5 py-1 text-xs font-medium text-blue-500">
                        <CheckCircle2 className="w-3 h-3 shrink-0" />
                        {formatMethodName(imp.method_used)}
                      </span>
                    ) : isLowConfidence ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-warning/12 px-2.5 py-1 text-xs font-medium text-warning-fg">
                        <AlertTriangle className="w-3 h-3 shrink-0" />
                        {formatMethodName(imp.method_used)}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-success/12 px-2.5 py-1 text-xs font-medium text-success-fg">
                        {formatMethodName(imp.method_used)}
                      </span>
                    )}

                    {/* A routed method is a recommendation. Changing it here
                        re-runs that column against the same data. */}
                    {!isFlag && !isNotImplemented && (
                      <label className="flex items-center gap-1.5">
                        <span className="sr-only">Imputation method for {imp.target_column}</span>
                        <select
                          value={overrides[imp.target_column] ?? imp.method_used.toLowerCase()}
                          disabled={rerunning}
                          onChange={(e) => {
                            const next = e.target.value;
                            setOverrides((prev) => {
                              const copy = { ...prev };
                              // Selecting the method already in use is not a change.
                              if (next === imp.method_used.toLowerCase()) delete copy[imp.target_column];
                              else copy[imp.target_column] = next;
                              return copy;
                            });
                          }}
                          className={`rounded-full border px-2.5 py-1 text-xs font-medium bg-white transition-colors disabled:opacity-50 ${
                            overrides[imp.target_column]
                              ? "border-blue-500/50 text-blue-600"
                              : "border-gray-200 text-gray-600 hover:border-gray-300"
                          }`}
                        >
                          {Array.from(
                            new Set([imp.method_used.toLowerCase(), ...RERUN_METHODS])
                          ).map((m) => (
                            <option key={m} value={m}>
                              {formatMethodName(m)}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                  </div>
                </div>

                {/* Why those cells were left alone. Refusing to fill them is
                    usually the correct call, but only if it is stated. */}
                {!isFlag && (imp.n_unimputable ?? 0) > 0 && imp.unimputable_reason && (
                  <p className="text-xs text-warning-fg leading-relaxed bg-warning/8 border border-warning/20 px-3.5 py-2.5 rounded-2xl">
                    <span className="font-semibold">Left missing on purpose. </span>
                    {imp.unimputable_reason}
                  </p>
                )}

                {isFlag ? (
                  <p className="text-xs font-medium text-blue-500 flex items-center gap-1.5 bg-blue-500/8 px-3 py-2 rounded-full w-fit">
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    Structural handling — indicator column added, no statistical imputation needed.
                  </p>
                ) : isLowConfidence ? (
                  <p className="text-xs font-medium text-warning-fg flex items-center gap-1.5 bg-warning/8 px-3 py-2 rounded-full w-fit">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                    This is a cautious default — see the Diagnosis tab for why the pattern was unclear.
                  </p>
                ) : null}

                {/* LLM-generated explanation -- kept visually distinct from
                    the method badge/status above, so it reads as the model's
                    own reasoning rather than a system-generated caption. */}
                <div className="rounded-2xl bg-gray-100/70 px-4 py-3.5 flex gap-3">
                  <div className="w-6 h-6 rounded-full bg-blue-500/10 flex items-center justify-center shrink-0 mt-0.5">
                    <Sparkles className="w-3 h-3 text-blue-500" strokeWidth={2} />
                  </div>
                  <div className="min-w-0">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-1">
                      AI explanation
                    </p>
                    <p className="text-sm text-gray-700 leading-relaxed">
                      {imp.rationale}
                    </p>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </div>
  );
}