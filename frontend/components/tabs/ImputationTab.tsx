"use client";

import { useAppSelector } from "@/store/hooks";
import { useState } from "react";
import { Download, AlertTriangle, CheckCircle2, HelpCircle, Sparkles } from "lucide-react";
import { downloadCleanedCsv } from "@/lib/api";
import { motion } from "framer-motion";

const EASE = [0.22, 1, 0.36, 1] as const;

function isFlagOnly(method?: string | null): boolean {
  if (!method) return false;
  const lower = method.trim().toLowerCase().replace(/[- ]/g, "_");
  return lower === "flag_only";
}

function formatMethodName(method: string): string {
  if (method === "not_implemented") return "Not yet supported";
  const lower = method.trim().toLowerCase().replace(/[- ]/g, "_");
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
  const [downloading, setDownloading] = useState(false);

  if (!activeResults) return null;
  const { imputation_results = [], dataset } = activeResults;

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
          <h1 className="text-3xl font-semibold text-[#1D1D1F] tracking-tight">
            Imputation
          </h1>
          <p className="text-sm text-[#6E6E73] mt-1.5">
            How missing values were filled in, and why.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE, delay: 0.05 }}
          className="rounded-[28px] border border-white/50 bg-white/90 backdrop-blur-xl shadow-[0_8px_30px_rgba(0,0,0,0.06)] px-10 py-16 text-center"
        >
          <div className="w-12 h-12 rounded-2xl bg-[#F5F5F7] flex items-center justify-center mx-auto mb-4">
            <HelpCircle className="w-5 h-5 text-[#AEAEB2]" strokeWidth={1.5} />
          </div>
          <p className="text-sm text-[#6E6E73]">
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
        <h1 className="text-3xl font-semibold text-[#1D1D1F] tracking-tight">
          Imputation
        </h1>
        <p className="text-sm text-[#6E6E73] mt-1.5">
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
          className="rounded-[24px] border border-white/50 bg-white/90 backdrop-blur-xl px-6 py-5 shadow-[0_4px_12px_rgba(0,0,0,0.04)]"
        >
          <p className="text-sm text-[#6E6E73] mb-2">Values filled in</p>
          <p className="text-3xl font-semibold tabular-nums text-[#1D1D1F]">
            {totalValuesFilled.toLocaleString()}
          </p>
        </motion.div>
        {(totalFlaggedLeftNull > 0 || flaggedCols.length > 0) && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: EASE, delay: 0.045 }}
            whileHover={{ y: -2 }}
            className="rounded-[24px] border border-white/50 bg-white/90 backdrop-blur-xl px-6 py-5 shadow-[0_4px_12px_rgba(0,0,0,0.04)]"
          >
            <p className="text-sm text-[#6E6E73] mb-2">Structural / Flagged</p>
            <p className="text-3xl font-semibold tabular-nums text-[#0071E3]">
              {totalFlaggedLeftNull.toLocaleString()}
            </p>
          </motion.div>
        )}
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE, delay: 0.06 }}
          whileHover={{ y: -2 }}
          className="rounded-[24px] border border-white/50 bg-white/90 backdrop-blur-xl px-6 py-5 shadow-[0_4px_12px_rgba(0,0,0,0.04)]"
        >
          <p className="text-sm text-[#6E6E73] mb-2">Resolved confidently</p>
          <p className="text-3xl font-semibold tabular-nums text-[#1D1D1F]">
            {resolvedCols.length.toLocaleString()}
          </p>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE, delay: 0.09 }}
          whileHover={{ y: -2 }}
          className="rounded-[24px] border border-white/50 bg-white/90 backdrop-blur-xl px-6 py-5 shadow-[0_4px_12px_rgba(0,0,0,0.04)]"
        >
          <p className="text-sm text-[#6E6E73] mb-2">Ambiguous, needs review</p>
          <p className="text-3xl font-semibold tabular-nums text-[#FFB340]">
            {(lowConfidenceCols.length + notImplementedCols.length).toLocaleString()}
          </p>
        </motion.div>
      </div>

      {/* 3. Download / status banner */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: EASE, delay: 0.1 }}
        className={`rounded-[28px] backdrop-blur-xl shadow-[0_4px_12px_rgba(0,0,0,0.04)] px-7 py-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-5 ${
          notImplementedCols.length > 0
            ? "bg-[#FFB340]/8 border border-[#FFB340]/25"
            : "bg-white/90 border border-white/50"
        }`}
      >
        <div className="flex items-start gap-3.5">
          <div
            className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
              notImplementedCols.length > 0 ? "bg-[#FFB340]/15" : "bg-[#34C759]/12"
            }`}
          >
            {notImplementedCols.length > 0 ? (
              <AlertTriangle className="w-4.5 h-4.5 text-[#B8791F]" strokeWidth={1.75} />
            ) : (
              <CheckCircle2 className="w-4.5 h-4.5 text-[#1F8A3D]" strokeWidth={1.75} />
            )}
          </div>
          <div>
            <h2 className="text-lg font-medium text-[#1D1D1F]">
              {canDownloadAll ? "Cleaned dataset ready" : "Partial imputation completed"}
            </h2>
            <p className="text-sm text-[#6E6E73] mt-1 leading-relaxed max-w-xl">
              {canDownloadAll ? (
                "All affected columns have been filled in and merged into your cleaned dataset."
              ) : notImplementedCols.length > 0 ? (
                <>
                  {notImplementedCols.length} column{notImplementedCols.length > 1 ? "s" : ""} with
                  text categories couldn&apos;t be automatically filled in yet — the download will
                  still include the remaining gaps in{" "}
                  <span className="font-medium text-[#8A5A14]">
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
          className="inline-flex items-center justify-center gap-2.5 bg-[#0071E3] hover:bg-[#0077ED] text-white text-sm font-medium px-6 py-3 rounded-full shadow-[0_4px_12px_rgba(0,113,227,0.25)] hover:shadow-[0_6px_16px_rgba(0,113,227,0.32)] transition-shadow duration-300 shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
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
          <h2 className="text-xl font-semibold tracking-tight text-[#1D1D1F]">
            Applied methods &amp; rationale
          </h2>
          <p className="text-sm text-[#6E6E73] mt-1">
            Columns needing a closer look are listed first.
          </p>
        </motion.div>

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
                className={`rounded-[28px] border bg-white/90 backdrop-blur-xl shadow-[0_4px_12px_rgba(0,0,0,0.04)] px-6 py-5 space-y-3.5 ${
                  isNotImplemented
                    ? "border-[#AEAEB2]/30"
                    : isLowConfidence
                    ? "border-[#FFB340]/25"
                    : isFlag
                    ? "border-[#0071E3]/25"
                    : "border-white/50"
                }`}
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3.5 border-b border-[#F5F5F7]">
                  <div className="flex items-center flex-wrap gap-2.5">
                    <span className="font-mono font-medium text-base text-[#1D1D1F] bg-[#F5F5F7] px-3 py-1.5 rounded-full">
                      {imp.target_column}
                    </span>
                    {imp.semantic_role && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#0071E3]/10 px-2.5 py-1 text-xs font-medium text-[#0071E3]">
                        {formatSemanticRole(imp.semantic_role)}
                      </span>
                    )}
                    <span className="text-xs font-medium text-[#8E8E93] tabular-nums">
                      {isFlagOnly(imp.method_used)
                        ? `${imp.n_imputed.toLocaleString()} flagged, left null`
                        : `${imp.n_imputed.toLocaleString()} values filled in`}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 shrink-0 self-start sm:self-auto">
                    {isNotImplemented ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#F5F5F7] px-2.5 py-1 text-xs font-medium text-[#6E6E73]">
                        Not yet supported
                      </span>
                    ) : isFlag ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-[#0071E3]/12 px-2.5 py-1 text-xs font-medium text-[#0071E3]">
                        <CheckCircle2 className="w-3 h-3 shrink-0" />
                        {formatMethodName(imp.method_used)}
                      </span>
                    ) : isLowConfidence ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-[#FFB340]/12 px-2.5 py-1 text-xs font-medium text-[#B8791F]">
                        <AlertTriangle className="w-3 h-3 shrink-0" />
                        {formatMethodName(imp.method_used)}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#34C759]/12 px-2.5 py-1 text-xs font-medium text-[#1F8A3D]">
                        {formatMethodName(imp.method_used)}
                      </span>
                    )}
                  </div>
                </div>

                {isFlag ? (
                  <p className="text-xs font-medium text-[#0071E3] flex items-center gap-1.5 bg-[#0071E3]/8 px-3 py-2 rounded-full w-fit">
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                    Structural handling — indicator column added, no statistical imputation needed.
                  </p>
                ) : isLowConfidence ? (
                  <p className="text-xs font-medium text-[#B8791F] flex items-center gap-1.5 bg-[#FFB340]/8 px-3 py-2 rounded-full w-fit">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                    This is a cautious default — see the Diagnosis tab for why the pattern was unclear.
                  </p>
                ) : null}

                {/* LLM-generated explanation -- kept visually distinct from
                    the method badge/status above, so it reads as the model's
                    own reasoning rather than a system-generated caption. */}
                <div className="rounded-2xl bg-[#F5F5F7]/70 px-4 py-3.5 flex gap-3">
                  <div className="w-6 h-6 rounded-full bg-[#0071E3]/10 flex items-center justify-center shrink-0 mt-0.5">
                    <Sparkles className="w-3 h-3 text-[#0071E3]" strokeWidth={2} />
                  </div>
                  <div className="min-w-0">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-[#8E8E93] mb-1">
                      AI explanation
                    </p>
                    <p className="text-sm text-[#3A3A3C] leading-relaxed">
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