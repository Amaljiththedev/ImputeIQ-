"use client";

import { useAppSelector } from "@/store/hooks";
import { useState, useEffect } from "react";
import { AlertTriangle, ChevronDown, Sigma } from "lucide-react";
import { getMissingnessMatrix, type MissingnessMatrix } from "@/lib/api";
import { AnimatePresence, motion } from "framer-motion";

const EASE = [0.22, 1, 0.36, 1] as const;

function formatSemanticRole(role?: string | null) {
  if (!role) return null;
  const lower = role.toLowerCase();
  if (lower === "identifier") return "Key/ID";
  if (lower === "categorical") return "Categorical";
  if (lower === "continuous") return "Continuous";
  return role;
}

export default function DiagnosisTab() {
  const { activeResults } = useAppSelector((s) => s.dataset);
  const [matrixData, setMatrixData] = useState<MissingnessMatrix | null>(null);
  const [matrixLoading, setMatrixLoading] = useState<boolean>(true);
  const [matrixError, setMatrixError] = useState<string | null>(null);

  // Advanced section (pattern matrix) is collapsed by default -- it's the
  // most technical part of this tab and shouldn't compete with the
  // per-column breakdown for attention.
  const [matrixOpen, setMatrixOpen] = useState<boolean>(false);

  // Controlled accordion: allow multiple expanded, first item open by default
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => {
    if (!activeResults?.diagnosis_results?.length) return new Set();
    return new Set([activeResults.diagnosis_results[0].id]);
  });

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // Fetch missingness pattern matrix on mount
  useEffect(() => {
    const datasetId = activeResults?.dataset?.id;
    if (!datasetId) return;

    let mounted = true;
    queueMicrotask(() => {
      if (mounted) {
        setMatrixLoading(true);
        setMatrixError(null);
      }
    });

    getMissingnessMatrix(datasetId)
      .then((data) => {
        if (mounted) {
          setMatrixData(data);
          setMatrixLoading(false);
        }
      })
      .catch((err) => {
        if (mounted) {
          setMatrixError(err.message || "Failed to load missingness matrix");
          setMatrixLoading(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, [activeResults?.dataset?.id]);

  if (!activeResults) return null;
  const { diagnosis_results = [] } = activeResults;

  // Surface the columns that need attention first, so the most actionable
  // items aren't buried at the bottom of the list.
  const sortedDiagnoses = [...diagnosis_results].sort((a, b) => {
    const aAmbiguous = a.diagnosed_mechanism.startsWith("Ambiguous") ? 1 : 0;
    const bAmbiguous = b.diagnosed_mechanism.startsWith("Ambiguous") ? 1 : 0;
    if (aAmbiguous !== bAmbiguous) return bAmbiguous - aAmbiguous;
    return b.n_missing - a.n_missing;
  });

  // Helper to get color intensity for matrix cell
  const getCellColor = (val: number, isDiagonal: boolean) => {
    if (isDiagonal) return "bg-[#F5F5F7] text-[#AEAEB2] font-normal";
    const abs = Math.abs(val);
    if (abs < 0.05) return "bg-[#F5F5F7] text-[#6E6E73]";
    if (abs < 0.15) return "bg-[#FFB340]/10 text-[#B8791F] border border-[#FFB340]/20";
    if (abs < 0.3) return "bg-[#FFB340]/25 text-[#8A5A14] font-medium";
    if (abs < 0.5) return "bg-[#FFB340]/60 text-[#5C3A0D] font-semibold";
    return "bg-[#FFB340] text-white font-semibold shadow-[0_2px_6px_rgba(255,179,64,0.35)]";
  };

  return (
    <div className="space-y-8 pb-12">
      {/* 1. Page heading */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: EASE }}
      >
        <h1 className="text-3xl font-semibold text-[#1D1D1F] tracking-tight">
          Diagnosis
        </h1>
        <p className="text-sm text-[#6E6E73] mt-1.5">
          Full statistical detail behind each column&apos;s missingness classification.
        </p>
      </motion.div>

      {/* 2. Per-column detail list -- primary content on the page,
          with columns that need review surfaced first. */}
      <div className="space-y-4">
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: EASE, delay: 0.1 }}
        >
          <h2 className="text-xl font-semibold tracking-tight text-[#1D1D1F]">
            Per-column statistical breakdown
          </h2>
          <p className="text-sm text-[#6E6E73] mt-1">
            Columns needing review are listed first.
          </p>
        </motion.div>

        <div className="space-y-3">
          {sortedDiagnoses.map((diag, idx) => {
            const isExpanded = expandedIds.has(diag.id);
            const isAmbiguous = diag.diagnosed_mechanism.startsWith("Ambiguous");

            const catEntries = Object.entries(diag.categorical_assoc_p_values || {});
            const numEntries = Object.entries(diag.numeric_assoc_p_values || {});

            return (
              <motion.div
                key={diag.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, ease: EASE, delay: Math.min(idx * 0.03, 0.3) }}
                className={`rounded-[28px] border bg-white/90 backdrop-blur-xl shadow-[0_4px_12px_rgba(0,0,0,0.04)] overflow-hidden ${
                  isAmbiguous ? "border-[#FFB340]/25" : "border-white/50"
                }`}
              >
                {/* Header row (always visible, click to toggle) */}
                <button
                  type="button"
                  onClick={() => toggleExpand(diag.id)}
                  className="w-full px-6 py-5 flex items-center justify-between gap-4 hover:bg-[#F5F5F7]/60 transition-colors duration-200 text-left outline-none"
                >
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="font-medium font-mono text-base text-[#1D1D1F] bg-[#F5F5F7] px-3 py-1.5 rounded-full">
                      {diag.target_column}
                    </span>

                    {diag.semantic_role && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#0071E3]/10 px-2.5 py-1 text-xs font-medium text-[#0071E3]">
                        {formatSemanticRole(diag.semantic_role)}
                      </span>
                    )}

                    {isAmbiguous ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-[#FFB340]/12 px-2.5 py-1 text-xs font-medium text-[#B8791F]">
                        <AlertTriangle className="w-3 h-3 shrink-0" />
                        Uncertain
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#34C759]/12 px-2.5 py-1 text-xs font-medium text-[#1F8A3D]">
                        {diag.diagnosed_mechanism}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-xs font-medium text-[#8E8E93] tabular-nums">
                      {diag.n_missing.toLocaleString()} missing
                    </span>
                    <motion.span
                      animate={{ rotate: isExpanded ? 180 : 0 }}
                      transition={{ duration: 0.25, ease: EASE }}
                    >
                      <ChevronDown className="w-4 h-4 text-[#AEAEB2]" />
                    </motion.span>
                  </div>
                </button>

                {/* Expanded content */}
                <AnimatePresence initial={false}>
                  {isExpanded && (
                    <motion.div
                      key="content"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.3, ease: EASE }}
                      className="overflow-hidden"
                    >
                      <div className="px-6 pb-7 pt-4 space-y-6">
                        {/* Diagnosis detail verbatim */}
                        <div className="space-y-2">
                          <p className="text-xs font-medium text-[#AEAEB2] uppercase tracking-wider">
                            Diagnosis detail
                          </p>
                          <div className="bg-[#F5F5F7]/70 p-4 rounded-2xl font-mono text-xs sm:text-sm text-[#3A3A3C] leading-relaxed break-words">
                            {diag.diagnosis_detail}
                          </div>
                        </div>

                        {/* Little's MCAR test */}
                        <div className="space-y-2">
                          <p className="text-xs font-medium text-[#AEAEB2] uppercase tracking-wider">
                            Little&apos;s MCAR test
                          </p>
                          <div className="bg-[#F5F5F7]/70 px-4 py-3.5 rounded-2xl flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                            <span className="font-mono text-xs sm:text-sm text-[#3A3A3C]">
                              p-value:{" "}
                              <strong className="font-semibold text-[#1D1D1F] tabular-nums">
                                {diag.littles_p_value !== undefined && diag.littles_p_value !== null
                                  ? diag.littles_p_value.toFixed(4)
                                  : "N/A"}
                              </strong>
                            </span>
                            <div className="flex items-center gap-2">
                              <span className="text-xs text-[#8E8E93]">Verdict:</span>
                              {diag.littles_p_value !== undefined && diag.littles_p_value !== null ? (
                                diag.littles_suggests_mcar ? (
                                  <span className="inline-flex items-center gap-1 bg-white text-[#3A3A3C] px-2.5 py-1 rounded-full text-xs font-medium shadow-[0_1px_3px_rgba(0,0,0,0.06)]">
                                    Suggests MCAR
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 bg-[#FFB340]/15 text-[#8A5A14] px-2.5 py-1 rounded-full text-xs font-medium">
                                    Rejects MCAR
                                  </span>
                                )
                              ) : (
                                <span className="inline-flex items-center gap-1 bg-[#F5F5F7] text-[#8E8E93] px-2.5 py-1 rounded-full text-xs font-medium">
                                  Skipped (Identifier / Role-based)
                                </span>
                              )}
                            </div>
                          </div>
                        </div>

                        {/* Association tests */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {/* Categorical associations */}
                          <div className="space-y-2">
                            <p className="text-xs font-medium text-[#AEAEB2] uppercase tracking-wider">
                              Categorical associations
                            </p>
                            <div className="bg-[#F5F5F7]/70 rounded-2xl overflow-hidden">
                              {catEntries.length === 0 ? (
                                <p className="p-4 text-xs text-[#AEAEB2] italic">
                                  No categorical columns available for comparison
                                </p>
                              ) : (
                                <div className="divide-y divide-white/70">
                                  {catEntries.map(([colName, pVal]) => {
                                    const isDriver = diag.significant_drivers.includes(colName);
                                    return (
                                      <div
                                        key={colName}
                                        className={`px-4 py-2.5 flex items-center justify-between text-xs sm:text-sm transition-colors duration-200 ${
                                          isDriver
                                            ? "bg-[#0071E3]/8 text-[#0A3D74] font-medium"
                                            : "text-[#3A3A3C] hover:bg-white/60"
                                        }`}
                                      >
                                        <div className="flex items-center gap-2 truncate pr-2">
                                          <span className="font-mono truncate">{colName}</span>
                                          {isDriver && (
                                            <span className="bg-[#0071E3] text-white text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded-full tracking-wider shrink-0">
                                              Driver
                                            </span>
                                          )}
                                        </div>
                                        <span className="font-mono text-[#3A3A3C] shrink-0 tabular-nums">
                                          {typeof pVal === "number" ? pVal.toFixed(4) : (pVal ?? "N/A")}
                                        </span>
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                          </div>

                          {/* Numeric associations */}
                          <div className="space-y-2">
                            <p className="text-xs font-medium text-[#AEAEB2] uppercase tracking-wider">
                              Numeric associations
                            </p>
                            <div className="bg-[#F5F5F7]/70 rounded-2xl overflow-hidden">
                              {numEntries.length === 0 ? (
                                <p className="p-4 text-xs text-[#AEAEB2] italic">
                                  No numeric columns available for comparison
                                </p>
                              ) : (
                                <div className="divide-y divide-white/70">
                                  {numEntries.map(([colName, pVal]) => {
                                    const isDriver = diag.significant_drivers.includes(colName);
                                    return (
                                      <div
                                        key={colName}
                                        className={`px-4 py-2.5 flex items-center justify-between text-xs sm:text-sm transition-colors duration-200 ${
                                          isDriver
                                            ? "bg-[#0071E3]/8 text-[#0A3D74] font-medium"
                                            : "text-[#3A3A3C] hover:bg-white/60"
                                        }`}
                                      >
                                        <div className="flex items-center gap-2 truncate pr-2">
                                          <span className="font-mono truncate">{colName}</span>
                                          {isDriver && (
                                            <span className="bg-[#0071E3] text-white text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded-full tracking-wider shrink-0">
                                              Driver
                                            </span>
                                          )}
                                        </div>
                                        <span className="font-mono text-[#3A3A3C] shrink-0 tabular-nums">
                                          {typeof pVal === "number" ? pVal.toFixed(4) : (pVal ?? "N/A")}
                                        </span>
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* 4. Pattern matrix -- demoted to an advanced, collapsible section.
          It's the densest, most technical part of this tab, so it shouldn't
          compete with the per-column breakdown for the user's attention. */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: EASE, delay: 0.05 }}
        className="rounded-[28px] border border-white/50 bg-white/60 backdrop-blur-xl shadow-[0_4px_12px_rgba(0,0,0,0.04)] overflow-hidden"
      >
        <button
          type="button"
          onClick={() => setMatrixOpen((v) => !v)}
          className="w-full px-7 py-5 flex items-center justify-between gap-4 hover:bg-white/40 transition-colors duration-200 text-left outline-none"
        >
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-[#F5F5F7] flex items-center justify-center shrink-0">
              <Sigma className="w-4 h-4 text-[#6E6E73]" strokeWidth={1.75} />
            </div>
            <div>
              <h2 className="text-base font-semibold tracking-tight text-[#1D1D1F]">
                Missingness pattern matrix
              </h2>
              <p className="text-xs text-[#8E8E93] mt-0.5">
                Advanced &mdash; how often columns are missing together
              </p>
            </div>
          </div>
          <motion.span
            animate={{ rotate: matrixOpen ? 180 : 0 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="shrink-0"
          >
            <ChevronDown className="w-4 h-4 text-[#AEAEB2]" />
          </motion.span>
        </button>

        <AnimatePresence initial={false}>
          {matrixOpen && (
            <motion.div
              key="matrix-content"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: EASE }}
              className="overflow-hidden"
            >
              <div className="px-7 pb-7 pt-1 space-y-5">
                <p className="text-sm text-[#6E6E73] leading-relaxed">
                  Values near zero mean no relationship; higher values mean their gaps tend to overlap.
                </p>

                {matrixLoading && (
                  <div className="py-14 flex items-center justify-center text-sm text-[#8E8E93]">
                    <motion.span
                      animate={{ opacity: [0.4, 1, 0.4] }}
                      transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
                    >
                      Loading missingness pattern matrix…
                    </motion.span>
                  </div>
                )}

                {!matrixLoading && matrixError && (
                  <div className="p-4 rounded-2xl bg-[#FFB340]/10 border border-[#FFB340]/20 text-sm text-[#8A5A14]">
                    {matrixError}
                  </div>
                )}

                {!matrixLoading && !matrixError && matrixData && (
                  <>
                    {matrixData.columns.length < 2 ? (
                      <div className="py-6 text-sm text-[#6E6E73]">
                        Only one column has missing values, so there&apos;s no pattern to compare.
                      </div>
                    ) : (
                      <div className="space-y-3 pt-2">
                        <div className="overflow-x-auto pb-2 flex justify-center">
                          <div className="inline-block">
                            <table className="border-collapse mx-auto">
                              <thead>
                                <tr>
                                  <th className="p-2 text-left text-xs font-mono font-medium text-[#AEAEB2] sticky left-0 bg-white z-10">
                                    {/* Top-left corner */}
                                  </th>
                                  {matrixData.columns.map((colName) => (
                                    <th
                                      key={colName}
                                      className="p-2 text-center text-xs font-mono font-medium text-[#6E6E73] max-w-[100px] truncate"
                                      title={colName}
                                    >
                                      {colName}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {matrixData.columns.map((rowCol, i) => (
                                  <tr key={rowCol}>
                                    <th
                                      className="p-2 text-right pr-3 text-xs font-mono font-medium text-[#6E6E73] max-w-[120px] truncate sticky left-0 bg-white z-10"
                                      title={rowCol}
                                    >
                                      {rowCol}
                                    </th>
                                    {matrixData.columns.map((colCol, j) => {
                                      const val = matrixData.matrix[i]?.[j] ?? 0;
                                      const isDiagonal = i === j;
                                      const cellStyle = getCellColor(val, isDiagonal);

                                      return (
                                        <td key={`${rowCol}-${colCol}`} className="p-1 text-center">
                                          <div
                                            className={`w-12 h-12 sm:w-14 sm:h-14 rounded-2xl flex items-center justify-center text-xs font-mono transition-colors duration-200 mx-auto ${cellStyle}`}
                                            title={`${rowCol} × ${colCol}: ${val.toFixed(4)}`}
                                          >
                                            {isDiagonal ? "1.00" : val.toFixed(2)}
                                          </div>
                                        </td>
                                      );
                                    })}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                        <p className="text-xs text-[#AEAEB2] text-center">
                          Only columns with missing values are shown.
                        </p>
                      </div>
                    )}
                  </>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}