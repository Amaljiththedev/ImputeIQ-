"use client";

import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  Sparkles,
  FlaskConical,
  Play,
  CheckCircle2,
  RefreshCw,
  Database,
  FileSpreadsheet,
  AlertCircle,
  Loader2,
  Layers,
} from "lucide-react";
import { useAppDispatch } from "@/store/hooks";
import { addDataset, setActiveDataset } from "@/store/slices/datasetSlice";
import { setPhase, addLog } from "@/store/slices/jobSlice";
import {
  fetchSyntheticManifest,
  generateSyntheticData,
  loadSyntheticDataset,
  SyntheticManifest,
} from "@/lib/apiSynthetic";

interface SyntheticBenchmarkModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function SyntheticBenchmarkModal({
  isOpen,
  onClose,
}: SyntheticBenchmarkModalProps) {
  const dispatch = useAppDispatch();
  const [manifest, setManifest] = useState<SyntheticManifest | null>(null);
  const [loadingManifest, setLoadingManifest] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [loadingFile, setLoadingFile] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadManifest = async () => {
    setLoadingManifest(true);
    setError(null);
    try {
      const data = await fetchSyntheticManifest();
      setManifest(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load manifest.");
    } finally {
      setLoadingManifest(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      loadManifest();
    }
  }, [isOpen]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const updated = await generateSyntheticData();
      setManifest(updated);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to regenerate synthetic data.");
    } finally {
      setGenerating(false);
    }
  };

  const handleLoadDataset = async (outputFile: string) => {
    setLoadingFile(outputFile);
    setError(null);
    try {
      const dataset = await loadSyntheticDataset(outputFile);
      dispatch(addDataset(dataset));
      dispatch(setActiveDataset(dataset.id));
      dispatch(setPhase("validating"));
      dispatch(
        addLog(
          `Loaded synthetic benchmark dataset '${outputFile}'. Initializing Data Validation & missingness analysis...`
        )
      );
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `Failed to load ${outputFile}`);
    } finally {
      setLoadingFile(null);
    }
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 md:p-10 bg-black/40 backdrop-blur-sm overflow-y-auto">
        <motion.div
          initial={{ opacity: 0, scale: 0.96, y: 12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 12 }}
          transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          className="relative w-full max-w-4xl bg-white rounded-3xl shadow-2xl border border-gray-200/80 overflow-hidden flex flex-col max-h-[90vh]"
        >
          {/* Header */}
          <div className="px-8 py-6 bg-gradient-to-r from-blue-600 to-indigo-600 text-white flex items-center justify-between shrink-0">
            <div className="flex items-center gap-3">
              <div className="w-11 h-11 rounded-2xl bg-white/10 backdrop-blur-md flex items-center justify-center text-white">
                <FlaskConical className="w-6 h-6" strokeWidth={2} />
              </div>
              <div>
                <h3 className="text-xl font-bold tracking-tight">
                  Synthetic Benchmark & Evaluation Suite
                </h3>
                <p className="text-xs text-blue-100 mt-0.5">
                  Academic ground-truth generator (`cardio_train`) for mechanism validation
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center text-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Content Body */}
          <div className="p-8 overflow-y-auto flex-1 space-y-8 text-gray-900">
            {error && (
              <div className="p-4 rounded-2xl bg-red-50 border border-red-200 text-red-700 text-sm flex items-center gap-3">
                <AlertCircle className="w-5 h-5 shrink-0 text-red-500" />
                <span>{error}</span>
              </div>
            )}

            {/* Controls bar */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-5 rounded-2xl bg-[#FAFAFA] border border-gray-200/80">
              <div className="flex items-center gap-3">
                <Database className="w-5 h-5 text-indigo-600" />
                <div>
                  <div className="text-sm font-semibold text-gray-900">
                    Source Dataset: {manifest?.source ?? "cardio_train_ground_truth.csv"}
                  </div>
                  <div className="text-xs text-gray-500">
                    {manifest ? `${manifest.n_rows.toLocaleString()} rows · Seed: ${manifest.seed}` : "Loading source info..."}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 w-full sm:w-auto">
                <button
                  onClick={handleGenerate}
                  disabled={generating || loadingManifest}
                  className="flex-1 sm:flex-none flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium rounded-xl bg-white hover:bg-gray-50 text-gray-700 border border-gray-300 shadow-sm transition-colors disabled:opacity-50"
                >
                  {generating ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
                      <span>Regenerating...</span>
                    </>
                  ) : (
                    <>
                      <RefreshCw className="w-4 h-4 text-indigo-600" />
                      <span>Regenerate Ground Truth</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {loadingManifest ? (
              <div className="py-16 flex flex-col items-center justify-center text-gray-500">
                <Loader2 className="w-8 h-8 animate-spin text-indigo-600 mb-3" />
                <span className="text-sm font-medium">Loading synthetic manifest...</span>
              </div>
            ) : manifest ? (
              <>
                {/* Combined Dataset Hero Card */}
                <div className="p-6 rounded-2xl bg-gradient-to-br from-indigo-50/80 to-blue-50/50 border border-indigo-100/80 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6 shadow-sm">
                  <div className="flex items-start gap-4">
                    <div className="w-12 h-12 rounded-2xl bg-indigo-600 text-white flex items-center justify-center shrink-0 shadow-md shadow-indigo-600/20">
                      <Layers className="w-6 h-6" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h4 className="text-base font-bold text-gray-900">
                          Combined Multi-Column Benchmark
                        </h4>
                        <span className="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-indigo-100 text-indigo-800">
                          Recommended
                        </span>
                      </div>
                      <p className="text-xs text-gray-600 mt-1 max-w-xl leading-relaxed">
                        Contains simultaneous synthetic missingness across all 6 columns (`weight`, `alco`, `ap_hi`, `gluc`, `cholesterol`, `smoke`) following exact academic MCAR, MAR, and MNAR rules.
                      </p>
                    </div>
                  </div>

                  <button
                    onClick={() => handleLoadDataset("cardio_train_corrupted_combined.csv")}
                    disabled={!!loadingFile}
                    className="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold shadow-md shadow-indigo-600/20 transition-all flex items-center justify-center gap-2 shrink-0 disabled:opacity-50"
                  >
                    {loadingFile === "cardio_train_corrupted_combined.csv" ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Loading...</span>
                      </>
                    ) : (
                      <>
                        <Play className="w-4 h-4 fill-current" />
                        <span>Load & Test Benchmark</span>
                      </>
                    )}
                  </button>
                </div>

                {/* Individual Column Rules & Datasets Table */}
                <div>
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3 px-1">
                    Individual Column Injections & Ground-Truth Rules
                  </h4>
                  <div className="overflow-x-auto border border-gray-200 rounded-2xl bg-white shadow-sm">
                    <table className="w-full text-left border-collapse">
                      <thead>
                        <tr className="border-b border-gray-200 bg-gray-50/80 text-xs font-semibold text-gray-600 uppercase tracking-wider">
                          <th className="py-3 px-4">Column</th>
                          <th className="py-3 px-4">Mechanism</th>
                          <th className="py-3 px-4">Actual Missing</th>
                          <th className="py-3 px-4">Driver / Rule</th>
                          <th className="py-3 px-4 text-right">Single File</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 text-sm">
                        {manifest.generated_files.map((record) => {
                          const isMcar = record.mechanism.toUpperCase() === "MCAR";
                          const isMar = record.mechanism.toUpperCase() === "MAR";
                          const isMnar = record.mechanism.toUpperCase() === "MNAR";

                          return (
                            <tr key={record.output_file} className="hover:bg-gray-50/60 transition-colors">
                              <td className="py-3.5 px-4 font-semibold text-gray-900 tabular-nums">
                                {record.target_column}
                              </td>
                              <td className="py-3.5 px-4">
                                <span
                                  className={`inline-flex items-center px-2.5 py-0.5 rounded-md text-xs font-bold uppercase tracking-wide ${
                                    isMcar
                                      ? "bg-blue-100 text-blue-800"
                                      : isMar
                                      ? "bg-amber-100 text-amber-800"
                                      : "bg-purple-100 text-purple-800"
                                  }`}
                                >
                                  {record.mechanism}
                                </span>
                              </td>
                              <td className="py-3.5 px-4 tabular-nums text-gray-700">
                                {record.actual_missing_count} rows ({record.actual_missing_pct}%)
                              </td>
                              <td className="py-3.5 px-4 max-w-xs text-xs text-gray-600">
                                {record.driver_column && (
                                  <div className="font-semibold text-gray-800 mb-0.5">
                                    Driver: `{record.driver_column}`
                                  </div>
                                )}
                                <div className="line-clamp-2">
                                  {manifest.columns[record.target_column]?.rule || "Uniform random masking."}
                                </div>
                              </td>
                              <td className="py-3.5 px-4 text-right">
                                <button
                                  onClick={() => handleLoadDataset(record.output_file)}
                                  disabled={!!loadingFile}
                                  className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-gray-100 hover:bg-gray-200 text-gray-800 transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
                                >
                                  {loadingFile === record.output_file ? (
                                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  ) : (
                                    <FileSpreadsheet className="w-3.5 h-3.5 text-gray-600" />
                                  )}
                                  <span>Load File</span>
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            ) : (
              <div className="py-12 text-center text-sm text-gray-500">
                No synthetic manifest available. Click Regenerate above to build the benchmark files.
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-8 py-4 bg-gray-50 border-t border-gray-200 flex justify-end shrink-0">
            <button
              onClick={onClose}
              className="px-5 py-2 text-sm font-semibold rounded-xl bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 shadow-sm transition-colors"
            >
              Close
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
