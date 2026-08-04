"use client";

import { useEffect, useState } from "react";
import { 
  AlertTriangle, 
  CheckCircle2, 
  Database, 
  FileCheck, 
  Loader2, 
  Sparkles, 
  Table as TableIcon, 
  ChevronDown, 
  ChevronUp,
  Info
} from "lucide-react";
import { getValidationProfile, applyValidation, ValidationProfileResponse, PlaceholderCandidateOut } from "@/lib/api";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setCurrentJobId, setPhase, addLog } from "@/store/slices/jobSlice";

export default function ValidationGate() {
  const dispatch = useAppDispatch();
  const activeDatasetId = useAppSelector((state) => state.dataset.activeDatasetId);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [profileData, setProfileData] = useState<ValidationProfileResponse | null>(null);
  
  // Track checked state for each placeholder candidate (key: `${candidate.column}:${candidate.placeholder_value}`)
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const [showStatsTable, setShowStatsTable] = useState(false);

  useEffect(() => {
    if (!activeDatasetId) return;
    let isMounted = true;

    async function loadProfile() {
      setLoading(true);
      setError(null);
      try {
        const data = await getValidationProfile(activeDatasetId!);
        if (!isMounted) return;
        setProfileData(data);

        // Default-select candidates where Gemini/heuristic recommended conversion
        const initialSelected: Record<string, boolean> = {};
        data.candidates.forEach((cand) => {
          const key = `${cand.column}:${cand.placeholder_value}`;
          initialSelected[key] = cand.action === "replace_with_nan" || cand.recommendation.toLowerCase().includes("convert");
        });
        setSelected(initialSelected);
      } catch (err: unknown) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : "Failed to load dataset validation profile.");
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    }

    loadProfile();
    return () => {
      isMounted = false;
    };
  }, [activeDatasetId]);

  const handleToggleCandidate = (candidate: PlaceholderCandidateOut) => {
    const key = `${candidate.column}:${candidate.placeholder_value}`;
    setSelected((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const handleApplyChanges = async (applySelected: boolean) => {
    if (!activeDatasetId) return;
    setSubmitting(true);
    try {
      const replacements: Array<{ column: string; placeholder_value: any }> = [];
      if (applySelected && profileData) {
        profileData.candidates.forEach((cand) => {
          const key = `${cand.column}:${cand.placeholder_value}`;
          if (selected[key]) {
            replacements.push({
              column: cand.column,
              placeholder_value: cand.placeholder_value,
            });
          }
        });
      }

      const job = await applyValidation(activeDatasetId, replacements);
      dispatch(setCurrentJobId(job.id));
      dispatch(setPhase("diagnosing"));
      if (replacements.length > 0) {
        dispatch(addLog(`Applied ${replacements.length} placeholder conversions to validated copy (` +
          replacements.map(r => `${r.column}=${r.placeholder_value}`).join(", ") + `). Starting missingness diagnosis...`));
      } else {
        dispatch(addLog("Proceeding with original dataset values without placeholder conversion. Starting missingness diagnosis..."));
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to apply validation settings.");
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center p-16 bg-white rounded-2xl shadow-sm border border-slate-100 min-h-[400px]">
        <Loader2 className="w-10 h-10 text-blue-600 animate-spin mb-4" />
        <h3 className="text-lg font-semibold text-slate-800">Profiling Dataset & Analyzing Placeholders...</h3>
        <p className="text-sm text-slate-500 mt-1 max-w-md text-center">
          Checking distributions, null frequencies, and querying Gemini semantic validation for suspicious zero or sentinel values.
        </p>
      </div>
    );
  }

  if (error || !profileData) {
    return (
      <div className="p-8 bg-red-50 border border-red-200 rounded-2xl flex flex-col items-center text-center">
        <AlertTriangle className="w-10 h-10 text-red-600 mb-3" />
        <h3 className="text-lg font-semibold text-red-900">Validation Profiling Failed</h3>
        <p className="text-sm text-red-700 mt-1 max-w-md">{error || "No validation data received."}</p>
        <button
          onClick={() => handleApplyChanges(false)}
          className="mt-6 px-5 py-2.5 bg-red-600 hover:bg-red-700 text-white font-medium rounded-xl transition-colors text-sm"
        >
          Skip Validation & Continue to Diagnosis →
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header Banner */}
      <div className="bg-gradient-to-r from-blue-600 to-indigo-700 rounded-2xl p-6 text-white shadow-md flex items-start justify-between">
        <div>
          <div className="inline-flex items-center gap-2 bg-white/20 backdrop-blur-sm px-3 py-1 rounded-full text-xs font-semibold mb-3">
            <Sparkles className="w-3.5 h-3.5" />
            Preprocessing & Data Validation Layer
          </div>
          <h2 className="text-2xl font-bold">Inspect & Validate Placeholder Missing Values</h2>
          <p className="text-blue-100 text-sm mt-1 max-w-2xl">
            Some datasets (e.g. medical or financial) encode missing observations as <span className="font-semibold text-white">0</span> or <span className="font-semibold text-white">-999</span> instead of <span className="font-semibold text-white">NaN</span>. Review Gemini semantic recommendations below before launching statistical diagnosis.
          </p>
        </div>
        <FileCheck className="w-12 h-12 text-blue-200/50 hidden sm:block" />
      </div>

      {/* Dataset Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <div className="bg-white p-5 rounded-2xl border border-slate-200/80 shadow-sm">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Dataset ID</span>
          <div className="text-lg font-bold text-slate-800 mt-1 font-mono truncate">{profileData.dataset_id.slice(0, 8)}...</div>
        </div>
        <div className="bg-white p-5 rounded-2xl border border-slate-200/80 shadow-sm">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Total Rows</span>
          <div className="text-2xl font-bold text-slate-800 mt-1">{profileData.row_count.toLocaleString()}</div>
        </div>
        <div className="bg-white p-5 rounded-2xl border border-slate-200/80 shadow-sm">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Total Columns</span>
          <div className="text-2xl font-bold text-slate-800 mt-1">{profileData.column_count}</div>
        </div>
        <div className="bg-white p-5 rounded-2xl border border-slate-200/80 shadow-sm">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Duplicate Rows</span>
          <div className="text-2xl font-bold text-slate-800 mt-1 flex items-center gap-2">
            {profileData.duplicate_count}
            {profileData.duplicate_count > 0 && <span className="text-xs text-amber-600 font-medium">(will be flagged)</span>}
          </div>
        </div>
      </div>

      {/* Potential Placeholders Review Section */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm overflow-hidden">
        <div className="p-6 border-b border-slate-100 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-amber-500" />
              Potential Placeholder Values Detected
            </h3>
            <p className="text-sm text-slate-500 mt-0.5">
              Select which candidate placeholder values should be converted to <code className="bg-slate-100 px-1.5 py-0.5 rounded text-xs font-mono">NaN</code> on the preprocessed copy before running diagnosis. Original raw file remains untouched.
            </p>
          </div>
          <div className="text-right text-xs text-slate-400">
            {profileData.candidates.length} candidates evaluated
          </div>
        </div>

        {profileData.candidates.length === 0 ? (
          <div className="p-10 text-center text-slate-500 flex flex-col items-center">
            <CheckCircle2 className="w-10 h-10 text-emerald-500 mb-2" />
            <span className="font-semibold text-slate-700">No suspicious placeholder values detected</span>
            <span className="text-xs text-slate-400 mt-0.5">All columns appear to use standard null/NaN representation or legitimate numeric ranges.</span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50/80 text-slate-600 text-xs font-semibold uppercase tracking-wider border-b border-slate-200">
                  <th className="py-3.5 px-6 w-12">Convert</th>
                  <th className="py-3.5 px-6">Column</th>
                  <th className="py-3.5 px-6">Placeholder Value</th>
                  <th className="py-3.5 px-6">Affected Rows</th>
                  <th className="py-3.5 px-6">Gemini Recommendation</th>
                  <th className="py-3.5 px-6">Confidence & Rationale</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-sm">
                {profileData.candidates.map((cand, idx) => {
                  const key = `${cand.column}:${cand.placeholder_value}`;
                  const isChecked = !!selected[key];
                  const isRecommendedConvert = cand.action === "replace_with_nan" || cand.recommendation.toLowerCase().includes("convert");

                  return (
                    <tr 
                      key={idx} 
                      className={`transition-colors hover:bg-slate-50/60 ${isChecked ? "bg-blue-50/30" : ""}`}
                    >
                      <td className="py-4 px-6">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => handleToggleCandidate(cand)}
                          className="w-4 h-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500 cursor-pointer"
                        />
                      </td>
                      <td className="py-4 px-6 font-semibold text-slate-800">{cand.column}</td>
                      <td className="py-4 px-6">
                        <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-mono font-medium bg-amber-100 text-amber-800 border border-amber-200">
                          {reprValue(cand.placeholder_value)}
                        </span>
                      </td>
                      <td className="py-4 px-6 font-medium text-slate-700">
                        {cand.count}{" "}
                        <span className="text-xs text-slate-400 font-normal">
                          ({((cand.count / profileData.row_count) * 100).toFixed(1)}%)
                        </span>
                      </td>
                      <td className="py-4 px-6">
                        <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold ${
                          isRecommendedConvert
                            ? "bg-blue-100 text-blue-800 border border-blue-200"
                            : "bg-emerald-100 text-emerald-800 border border-emerald-200"
                        }`}>
                          {isRecommendedConvert ? <Sparkles className="w-3 h-3" /> : <CheckCircle2 className="w-3 h-3" />}
                          {cand.recommendation}
                        </span>
                      </td>
                      <td className="py-4 px-6 max-w-md">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className="text-xs font-semibold text-slate-600">
                            Confidence: {(cand.confidence * 100).toFixed(0)}%
                          </span>
                          {cand.source && (
                            <span
                              className={`inline-flex items-center gap-1 text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-md ${
                                cand.source.toLowerCase() === "gemini"
                                  ? "bg-purple-100 text-purple-800 border border-purple-200"
                                  : "bg-slate-100 text-slate-700 border border-slate-200"
                              }`}
                            >
                              {cand.source.toLowerCase() === "gemini" ? "AI Verified (Gemini)" : "Heuristic Fallback"}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-slate-500 leading-relaxed">{cand.reason}</p>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Collapsible Data Quality Statistics Table */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm overflow-hidden">
        <button
          onClick={() => setShowStatsTable(!showStatsTable)}
          className="w-full p-5 flex items-center justify-between text-left hover:bg-slate-50/60 transition-colors"
        >
          <div className="flex items-center gap-2">
            <TableIcon className="w-5 h-5 text-slate-500" />
            <span className="font-bold text-slate-800">Full Column Profiling Statistics</span>
            <span className="text-xs text-slate-400 font-normal">({profileData.profiles.length} columns profiled)</span>
          </div>
          {showStatsTable ? <ChevronUp className="w-5 h-5 text-slate-400" /> : <ChevronDown className="w-5 h-5 text-slate-400" />}
        </button>

        {showStatsTable && (
          <div className="border-t border-slate-100 overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-50 text-slate-600 font-semibold uppercase tracking-wider border-b border-slate-200">
                  <th className="py-3 px-4">Column</th>
                  <th className="py-3 px-4">DType</th>
                  <th className="py-3 px-4 text-right">Min</th>
                  <th className="py-3 px-4 text-right">Max</th>
                  <th className="py-3 px-4 text-right">Mean</th>
                  <th className="py-3 px-4 text-right">Median</th>
                  <th className="py-3 px-4 text-right">Std</th>
                  <th className="py-3 px-4 text-right">Unique</th>
                  <th className="py-3 px-4 text-right">Nulls</th>
                  <th className="py-3 px-4 text-right">Zeros</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {profileData.profiles.map((p, idx) => (
                  <tr key={idx} className="hover:bg-slate-50/40">
                    <td className="py-2.5 px-4 font-semibold text-slate-800">{p.column}</td>
                    <td className="py-2.5 px-4 font-mono text-slate-500">{p.dtype}</td>
                    <td className="py-2.5 px-4 text-right font-mono">{p.min ?? "—"}</td>
                    <td className="py-2.5 px-4 text-right font-mono">{p.max ?? "—"}</td>
                    <td className="py-2.5 px-4 text-right font-mono">{p.mean !== null && p.mean !== undefined ? p.mean : "—"}</td>
                    <td className="py-2.5 px-4 text-right font-mono">{p.median !== null && p.median !== undefined ? p.median : "—"}</td>
                    <td className="py-2.5 px-4 text-right font-mono">{p.std !== null && p.std !== undefined ? p.std : "—"}</td>
                    <td className="py-2.5 px-4 text-right">{p.unique_count}</td>
                    <td className={`py-2.5 px-4 text-right font-semibold ${p.null_count > 0 ? "text-amber-600" : "text-slate-600"}`}>
                      {p.null_count}
                    </td>
                    <td className={`py-2.5 px-4 text-right font-semibold ${p.zero_count > 0 ? "text-blue-600" : "text-slate-600"}`}>
                      {p.zero_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Action Footer Buttons */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-2">
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Info className="w-4 h-4 text-slate-400 flex-shrink-0" />
          <span>Replacements are applied strictly to <code className="bg-slate-100 px-1 py-0.5 rounded font-mono">validated_df = df.copy()</code>. Original dataset stays untouched.</span>
        </div>

        <div className="flex items-center gap-3 w-full sm:w-auto">
          <button
            onClick={() => handleApplyChanges(false)}
            disabled={submitting}
            className="flex-1 sm:flex-initial px-5 py-3 border border-slate-300 hover:bg-slate-50 text-slate-700 font-semibold rounded-xl transition-colors text-sm disabled:opacity-50"
          >
            Skip & Keep Original Values
          </button>

          <button
            onClick={() => handleApplyChanges(true)}
            disabled={submitting}
            className="flex-1 sm:flex-initial px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-xl shadow-sm transition-all flex items-center justify-center gap-2 text-sm disabled:opacity-50"
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Applying & Starting Diagnosis...
              </>
            ) : (
              <>
                Apply Recommended Changes →
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

function reprValue(val: any): string {
  if (val === null || val === undefined) return "null";
  if (typeof val === "string" && val.trim() === "") return '"" (empty string)';
  return String(val);
}
