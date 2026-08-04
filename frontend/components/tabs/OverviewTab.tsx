"use client";

import { useAppSelector, useAppDispatch } from "@/store/hooks";
import { setActiveTab } from "@/store/slices/datasetSlice";
import { AlertTriangle, Download } from "lucide-react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";

const EASE = [0.22, 1, 0.36, 1] as const;

export default function OverviewTab() {
  const { activeResults, activeDatasetId } = useAppSelector((s) => s.dataset);
  const dispatch = useAppDispatch();
  const router = useRouter();

  if (!activeResults || !activeResults.dataset) return null;

  const {
    dataset,
    diagnosis_results = [],
    imputation_results = [],
    explanation_results = [],
  } = activeResults;

  const nAffected = diagnosis_results.length;
  const nConfident = diagnosis_results.filter(
    (r) => !r.diagnosed_mechanism.startsWith("Ambiguous")
  ).length;
  const nNeedReview = diagnosis_results.filter((r) =>
    r.diagnosed_mechanism.startsWith("Ambiguous")
  ).length;

  const diagMap = new Map(diagnosis_results.map((d) => [d.target_column, d]));
  const impMap = new Map(imputation_results.map((i) => [i.target_column, i]));
  const explanationColumns = explanation_results[0]?.columns_json || [];
  const expMap = new Map(explanationColumns.map((e) => [e.target_column, e]));

  const sortedColumns = [...(dataset.column_names || [])].sort((a, b) => {
    const missingA = diagMap.get(a)?.n_missing || 0;
    const missingB = diagMap.get(b)?.n_missing || 0;
    const hasMissingA = missingA > 0 ? 1 : 0;
    const hasMissingB = missingB > 0 ? 1 : 0;
    if (hasMissingA !== hasMissingB) return hasMissingB - hasMissingA;
    return a.localeCompare(b);
  });

  const allImputedReady =
    imputation_results.length > 0 &&
    imputation_results.every((r) => Boolean(r.imputed_file_path));
  const isOnlyDiagnosed =
    diagnosis_results.length > 0 && imputation_results.length === 0;

  // Fixed number of cells per heatmap row -- each cell represents a slice
  // of rows, colored by whether that slice falls within the missing
  // proportion for the column.
  const HEATMAP_CELLS = 40;

  return (
    <div className="w-full h-full flex flex-col min-h-0 overflow-y-auto">
      {/* items-start keeps each column at its natural height. Previously the
          grid was flex-1 + min-h-0 with inner overflow-y-auto scrollers, which
          meant the heatmap only got whatever vertical space the stat cards and
          benchmark card left over -- in practice ~27px, so it was invisible.
          One scroll region (the parent) instead of nested scroll traps. */}
      <div className="w-full grid grid-cols-1 lg:grid-cols-[1.8fr_1.2fr] gap-8 items-start">
        {/* Left column: stats + heatmap */}
        <div className="flex flex-col pr-2">
        <div className="grid grid-cols-3 gap-4 mb-7 shrink-0">
          <motion.div
            whileHover={{ y: -2 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="rounded-[24px] border border-white/50 bg-white/90 backdrop-blur-xl px-6 py-5 shadow-[0_4px_12px_rgba(0,0,0,0.04)]"
          >
            <p className="text-sm text-[#6E6E73] mb-2">Columns affected</p>
            <p className="text-3xl font-semibold tabular-nums text-[#1D1D1F]">
              {nAffected.toLocaleString()}
            </p>
          </motion.div>
          <motion.div
            whileHover={{ y: -2 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="rounded-[24px] border border-white/50 bg-white/90 backdrop-blur-xl px-6 py-5 shadow-[0_4px_12px_rgba(0,0,0,0.04)]"
          >
            <p className="text-sm text-[#6E6E73] mb-2">Confident diagnosis</p>
            <p className="text-3xl font-semibold tabular-nums text-[#1D1D1F]">
              {nConfident.toLocaleString()}
            </p>
          </motion.div>
          <motion.div
            whileHover={{ y: -2 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="rounded-[24px] border border-white/50 bg-white/90 backdrop-blur-xl px-6 py-5 shadow-[0_4px_12px_rgba(0,0,0,0.04)]"
          >
            <p className="text-sm text-[#6E6E73] mb-2">Need review</p>
            <p className="text-3xl font-semibold tabular-nums text-[#FFB340]">
              {nNeedReview.toLocaleString()}
            </p>
          </motion.div>
        </div>

        <div className="shrink-0 mb-5">
          <h3 className="text-xl font-semibold tracking-tight text-[#1D1D1F]">
            Missingness Heatmap
          </h3>
          <p className="text-sm text-[#6E6E73] mt-1.5 leading-relaxed">
            Each row is a column, and each cell represents a slice of your data rows.{" "}
            <span className="font-medium text-[#B8791F]">Amber</span> indicates missing values.
          </p>
        </div>

        <div className="pr-2">
          <div className="flex flex-col gap-4">
            {sortedColumns.map((colName, idx) => {
              const diag = diagMap.get(colName);
              const nMissing = diag?.n_missing ?? 0;
              const rowCount = dataset.row_count || 1;
              const pct = Math.min(1, Math.max(0, nMissing / rowCount));
              const missingCells = Math.round(pct * HEATMAP_CELLS);
              const pctDisplay = pct === 0 ? "0%" : `${(pct * 100).toFixed(0)}%`;

              return (
                <motion.div
                  key={colName}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, ease: EASE, delay: Math.min(idx * 0.015, 0.3) }}
                  className="flex items-center gap-4 hover:bg-white/70 p-2 -mx-2 rounded-2xl transition-colors duration-200"
                >
                  <code
                    className={`w-40 shrink-0 text-sm font-mono truncate ${
                      pct > 0 ? "text-[#1D1D1F] font-medium" : "text-[#8E8E93]"
                    }`}
                    title={`${colName} (${nMissing.toLocaleString()} missing out of ${rowCount.toLocaleString()} rows)`}
                  >
                    {colName}
                  </code>
                  <div className="flex flex-1 gap-[3px] h-4">
                    {Array.from({ length: HEATMAP_CELLS }).map((_, i) => (
                      <div
                        key={i}
                        className={`flex-1 rounded-[3px] transition-all duration-300 ${
                          i < missingCells
                            ? "bg-[#FFB340] shadow-[0_1px_2px_rgba(255,179,64,0.4)]"
                            : "bg-[#E8E8ED]"
                        }`}
                      />
                    ))}
                  </div>
                  <span
                    className={`w-12 shrink-0 text-sm text-right tabular-nums ${
                      pct > 0 ? "font-medium text-[#B8791F]" : "text-[#AEAEB2]"
                    }`}
                  >
                    {pctDisplay}
                  </span>
                </motion.div>
              );
            })}
          </div>
        </div>

        <div className="flex items-center gap-6 mt-5 pt-5 shrink-0">
          <span className="flex items-center gap-2 text-sm text-[#6E6E73]">
            <span className="w-3 h-3 rounded-full bg-[#E8E8ED] inline-block" />
            Present
          </span>
          <span className="flex items-center gap-2 text-sm text-[#6E6E73]">
            <span className="w-3 h-3 rounded-full bg-[#FFB340] inline-block" />
            Missing
          </span>
        </div>
      </div>

      {/* Right column: column list + primary action */}
      <div className="glass flex flex-col rounded-3xl px-6 py-6">
        <div className="shrink-0 mb-4">
          <h3 className="text-xl font-semibold tracking-tight text-[#1D1D1F]">
            Columns & Explanations
          </h3>
          <p className="text-sm text-[#6E6E73] mt-1.5">
            Click any column to view full diagnostic details.
          </p>
        </div>

        <div className="pr-1 -mx-1">
          {diagnosis_results.map((diag, i) => {
            const isAmbiguous = diag.diagnosed_mechanism.startsWith("Ambiguous");
            const exp = expMap.get(diag.target_column);
            const imp = impMap.get(diag.target_column);

            const summaryText =
              exp?.plain_language_summary ||
              `${diag.n_missing.toLocaleString()} missing, diagnosed as ${diag.diagnosed_mechanism}`;

            return (
              <motion.button
                key={diag.id}
                type="button"
                whileHover={{ scale: 1.005 }}
                whileTap={{ scale: 0.995 }}
                transition={{ duration: 0.2, ease: EASE }}
                onClick={() => dispatch(setActiveTab("diagnosis"))}
                className="w-full text-left py-4 px-4 mb-2 rounded-2xl transition-colors duration-200 hover:bg-[#F5F5F7] focus:outline-none focus:ring-2 focus:ring-[#0071E3]/25"
              >
                <div className="flex items-center justify-between gap-3 mb-2">
                  <code className="text-sm font-mono font-medium text-[#1D1D1F] break-words">
                    {diag.target_column}
                  </code>
                  {isAmbiguous ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-[#FFB340]/12 px-2.5 py-1 text-xs font-medium text-[#B8791F] shrink-0">
                      <AlertTriangle className="w-3.5 h-3.5" />
                      Uncertain
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded-full bg-[#34C759]/12 px-2.5 py-1 text-xs font-medium text-[#1F8A3D] shrink-0">
                      {diag.diagnosed_mechanism}
                    </span>
                  )}
                </div>
                <p className="text-sm text-[#6E6E73] leading-relaxed">
                  {summaryText}
                </p>
                {imp?.low_confidence && (
                  <p className="text-xs font-medium text-[#B8791F] mt-2.5 flex items-center gap-1.5 bg-[#FFB340]/10 py-1.5 px-2.5 rounded-full w-fit">
                    <AlertTriangle className="w-3 h-3" />
                    Review before relying on this recommendation
                  </p>
                )}
              </motion.button>
            );
          })}
        </div>

        <div className="shrink-0 pt-5 mt-auto">
          {allImputedReady && (
            <motion.a
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              transition={{ duration: 0.2, ease: EASE }}
              href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/datasets/${activeDatasetId}/download`}
              className="inline-flex items-center justify-center gap-2.5 bg-[#0071E3] hover:bg-[#0077ED] text-white text-base font-medium px-6 py-3.5 rounded-full shadow-[0_4px_12px_rgba(0,113,227,0.25)] hover:shadow-[0_6px_16px_rgba(0,113,227,0.32)] transition-shadow duration-300 w-full"
              download
            >
              <Download className="w-5 h-5" />
              Download Cleaned CSV
            </motion.a>
          )}

          {isOnlyDiagnosed && (
            <motion.button
              type="button"
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              transition={{ duration: 0.2, ease: EASE }}
              onClick={() => {
                if (activeDatasetId) {
                  router.push(`/datasets/${activeDatasetId}/approve`);
                }
              }}
              className="inline-flex items-center justify-center gap-2.5 bg-[#0071E3] hover:bg-[#0077ED] text-white text-base font-medium px-6 py-3.5 rounded-full shadow-[0_4px_12px_rgba(0,113,227,0.25)] hover:shadow-[0_6px_16px_rgba(0,113,227,0.32)] transition-shadow duration-300 w-full"
            >
              Review Recommendations →
            </motion.button>
          )}
        </div>
      </div>
    </div>
    </div>
  );
}