"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ArrowLeft, Loader2, Sparkles } from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { approveImputation, clarifyRecommendation, DiagnosisResult } from "@/lib/api";
import { setCurrentJobId, setPhase, clearCurrentJob, clearLogs } from "@/store/slices/jobSlice";
import { fetchResults } from "@/store/slices/datasetSlice";

interface ColumnRecommendation {
  columnName: string;
  mechanism: "MAR" | "Uncertain" | "Structural" | "Identifier" | string;
  recommendedMethod: string;
  isCautiousDefault: boolean;
  rationale: string;
  availableMethods: string[];
  structuralZeroWarning?: {
    flag: string;
    reason: string;
    name_pattern_match?: boolean;
  } | null;
  semanticRole?: string | null;
}

function formatMethodName(method: string): string {
  if (method === "not_implemented") return "Not yet supported";
  const lower = method.trim().toLowerCase();
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

function ColumnCard({
  rec,
  selectedMethod,
  onMethodChange,
  datasetId,
}: {
  rec: ColumnRecommendation;
  selectedMethod: string;
  onMethodChange: (method: string) => void;
  datasetId: string;
}) {
  const [question, setQuestion] = useState("");
  const [clarification, setClarification] = useState<string | null>(null);
  const [isAsking, setIsAsking] = useState(false);

  const handleAsk = async () => {
    if (!question.trim() || !datasetId) return;
    setIsAsking(true);
    try {
      const res = await clarifyRecommendation(datasetId, rec.columnName, question);
      setClarification(res.answer);
    } catch (err: any) {
      setClarification(err.message || "Failed to get clarification from assistant.");
    } finally {
      setIsAsking(false);
    }
  };

  return (
    <div className="rounded-2xl border border-gray-200/80 bg-white/95 p-6 shadow-sm space-y-4 transition-all hover:shadow-md">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2.5">
          <span className="text-[16px] font-semibold text-gray-900 font-mono tracking-tight">
            {rec.columnName}
          </span>
          {rec.semanticRole && (
            <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-blue-200/60">
              {formatSemanticRole(rec.semanticRole)}
            </span>
          )}
        </div>
        {rec.mechanism === "Structural" ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800 ring-1 ring-amber-300/80">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-700" />
            Structural Zero Candidate
          </span>
        ) : rec.mechanism === "Identifier" ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-3 py-1 text-xs font-semibold text-gray-700 ring-1 ring-gray-300/80">
            Identifier (No statistical imputation)
          </span>
        ) : rec.mechanism === "MAR" ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200/60">
            MAR
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 ring-1 ring-amber-200/60">
            <AlertTriangle className="w-3.5 h-3.5" />
            Uncertain / Cautious
          </span>
        )}
      </div>

      {/* Structural Zero Warning Banner */}
      {rec.structuralZeroWarning && (
        <div className="rounded-xl bg-amber-50/95 border border-amber-300/80 p-4 text-amber-950 flex gap-3 items-start shadow-sm">
          <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="text-xs font-bold uppercase tracking-wider text-amber-800">
              Domain-Knowledge Check Required
            </p>
            <p className="text-[13px] leading-relaxed text-amber-900">
              {rec.structuralZeroWarning.reason}
            </p>
          </div>
        </div>
      )}

      {/* Recommended method */}
      <div className="bg-gray-50/80 rounded-xl p-3.5 border border-gray-100/80">
        <p className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">Recommended Strategy</p>
        <p className="text-[15px] text-gray-900 font-semibold flex items-center gap-2">
          {formatMethodName(rec.recommendedMethod)}
          {rec.isCautiousDefault && (
            <span className="text-xs font-normal text-amber-600 bg-amber-50 border border-amber-200/60 px-2 py-0.5 rounded-md">
              Cautious Default
            </span>
          )}
        </p>
        <p className="text-[13px] text-gray-600 leading-relaxed mt-2">
          {rec.rationale}
        </p>
      </div>

      {/* Method select */}
      <div className="pt-1">
        <label
          htmlFor={`method-${rec.columnName}`}
          className="block text-xs font-medium text-gray-500 mb-1.5 uppercase tracking-wide"
        >
          Approved Imputation Method
        </label>
        <select
          id={`method-${rec.columnName}`}
          value={selectedMethod || rec.recommendedMethod}
          onChange={(e) => onMethodChange(e.target.value)}
          className="w-full appearance-none rounded-xl border border-gray-200 bg-gray-50/60 px-4 py-2.5 text-[14px] font-medium text-gray-900 outline-none transition-all focus:border-gray-400 focus:bg-white focus:ring-2 focus:ring-gray-900/5 cursor-pointer"
        >
          {rec.availableMethods.map((m) => (
            <option key={m} value={m}>
              {formatMethodName(m)}
              {m.toLowerCase() === rec.recommendedMethod.toLowerCase() ? " (Recommended)" : ""}
            </option>
          ))}
        </select>
      </div>

      {/* Ask a question */}
      <div className="pt-2 border-t border-gray-100">
        <label
          htmlFor={`question-${rec.columnName}`}
          className="flex items-center gap-1.5 text-xs font-medium text-gray-500 mb-2"
        >
          <Sparkles className="w-3.5 h-3.5 text-indigo-500" />
          Ask statistical assistant about this column
        </label>
        <div className="flex gap-2">
          <input
            id={`question-${rec.columnName}`}
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleAsk();
            }}
            placeholder="e.g. Why not use MICE if missing rate is low?"
            className="flex-1 rounded-xl border border-gray-200 bg-gray-50/60 px-3.5 py-2 text-[13px] text-gray-900 placeholder:text-gray-400 outline-none transition-colors focus:border-gray-400 focus:bg-white"
          />
          <button
            onClick={handleAsk}
            disabled={isAsking || !question.trim()}
            className="shrink-0 rounded-xl border border-gray-200 bg-white px-4 py-2 text-[13px] font-medium text-gray-700 transition-all hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
          >
            {isAsking ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              "Ask AI"
            )}
          </button>
        </div>

        {/* Clarification response */}
        {clarification && (
          <div className="mt-3 rounded-xl bg-indigo-50/60 border border-indigo-100 px-4 py-3 text-[13px] text-indigo-950 leading-relaxed animate-in fade-in slide-in-from-top-1 duration-300">
            <p className="text-xs font-semibold text-indigo-600 uppercase tracking-wider mb-1 flex items-center gap-1">
              <Sparkles className="w-3 h-3" /> Statistical Assistant Insight
            </p>
            {clarification}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ApprovalScreen() {
  const dispatch = useAppDispatch();
  const { activeDatasetId, activeResults } = useAppSelector((s) => s.dataset);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [selections, setSelections] = useState<Record<string, string>>({});

  useEffect(() => {
    if (activeDatasetId && !activeResults?.diagnosis_results?.length) {
      dispatch(fetchResults(activeDatasetId));
    }
  }, [activeDatasetId, activeResults?.diagnosis_results?.length, dispatch]);

  const rawDiagnoses = activeResults?.diagnosis_results || [];
  const derivedRecommendations: ColumnRecommendation[] = rawDiagnoses.map((diag) => {
    const isId =
      diag.semantic_role === "identifier" ||
      diag.recommended_method?.toLowerCase() === "flag_only" ||
      diag.diagnosed_mechanism?.toLowerCase().includes("identifier");
    const isCat = diag.semantic_role === "categorical" || diag.recommended_method?.toLowerCase() === "mode";
    const defaultMethods = isId
      ? ["flag_only"]
      : isCat
      ? ["mode", "zero"]
      : ["Median", "Mean", "KNN", "MICE", "Regression", "zero"];

    return {
      columnName: diag.target_column,
      mechanism: diag.structural_zero_warning
        ? "Structural"
        : isId
        ? "Identifier"
        : diag.diagnosed_mechanism?.includes("MAR")
        ? "MAR"
        : "Uncertain",
      recommendedMethod: diag.recommended_method || (isId ? "flag_only" : isCat ? "mode" : "Median"),
      isCautiousDefault: Boolean(diag.is_cautious_default),
      rationale: diag.rationale || "Theoretically selected based on diagnosed missingness patterns and distribution tests.",
      availableMethods: diag.available_methods || defaultMethods,
      structuralZeroWarning: diag.structural_zero_warning || null,
      semanticRole: diag.semantic_role || (isId ? "identifier" : isCat ? "categorical" : "continuous"),
    };
  });

  useEffect(() => {
    if (derivedRecommendations.length > 0 && Object.keys(selections).length === 0) {
      const initial: Record<string, string> = {};
      for (const rec of derivedRecommendations) {
        initial[rec.columnName] = rec.recommendedMethod;
      }
      setSelections(initial);
    }
  }, [derivedRecommendations, selections]);

  const handleMethodChange = (columnName: string, method: string) => {
    setSelections((prev) => ({ ...prev, [columnName]: method }));
  };

  const handleContinue = async () => {
    if (!activeDatasetId || isSubmitting) return;
    setIsSubmitting(true);
    dispatch(clearLogs());
    dispatch(setPhase("imputing"));
    try {
      const res = await approveImputation(activeDatasetId, selections);
      const status = (res.status || "").toLowerCase();
      const phase = (res.current_phase || "").toLowerCase();
      if (status === "complete" || status === "completed" || phase === "complete") {
        dispatch(setPhase("complete"));
      } else {
        dispatch(setCurrentJobId(res.id));
      }
    } catch (err: any) {
      console.error("Failed to submit approved methods:", err);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!activeResults) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
        <p className="text-sm text-gray-500 font-medium">Loading recommendations from database…</p>
      </div>
    );
  }

  if (rawDiagnoses.length === 0) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-16 text-center">
        <div className="bg-white rounded-3xl p-8 border border-gray-200/80 shadow-sm space-y-4">
          <div className="w-12 h-12 bg-emerald-50 text-emerald-600 rounded-2xl flex items-center justify-center mx-auto text-xl font-bold">
            ✓
          </div>
          <h2 className="text-xl font-bold text-gray-900">No Missing Values Detected</h2>
          <p className="text-sm text-gray-600 max-w-md mx-auto leading-relaxed">
            Our diagnostic scan verified all columns in this dataset. No missing data or gaps were found requiring imputation or repair.
          </p>
          <div className="pt-4">
            <button
              onClick={() => {
                dispatch(clearCurrentJob());
                dispatch(setPhase("complete"));
              }}
              className="rounded-xl bg-[#1D1D1F] px-6 py-2.5 text-sm font-medium text-white transition-all hover:bg-black shadow-md"
            >
              Proceed to Overview Dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      {/* Heading */}
      <div className="mb-8 bg-white/60 backdrop-blur-md rounded-2xl p-6 border border-gray-100 shadow-sm">
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight mb-2">
          Human-in-the-Loop Imputation Gate
        </h1>
        <p className="text-[15px] text-gray-600 leading-relaxed">
          Review our recommended strategy for each missing column before imputation is executed. No data modification occurs without your explicit approval.
        </p>
      </div>

      {/* Column cards */}
      <div className="space-y-4 mb-10">
        {derivedRecommendations.map((rec) => (
          <ColumnCard
            key={rec.columnName}
            rec={rec}
            selectedMethod={selections[rec.columnName] || rec.recommendedMethod}
            onMethodChange={(method) => handleMethodChange(rec.columnName, method)}
            datasetId={activeDatasetId || ""}
          />
        ))}
      </div>

      {/* Action buttons */}
      <div className="flex items-center justify-end gap-3 sticky bottom-6 bg-white/90 backdrop-blur-xl p-4 rounded-2xl border border-gray-200/80 shadow-lg">
        <button
          onClick={() => {
            dispatch(clearCurrentJob());
            dispatch(setPhase("idle"));
          }}
          disabled={isSubmitting}
          className="rounded-xl border border-gray-200 bg-white px-5 py-2.5 text-[14px] font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          onClick={handleContinue}
          disabled={isSubmitting}
          className="rounded-xl bg-[#1D1D1F] px-6 py-2.5 text-[14px] font-medium text-white transition-all hover:bg-black flex items-center gap-2 shadow-md disabled:opacity-50"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Submitting Approval…
            </>
          ) : (
            "Approve & Execute Imputation"
          )}
        </button>
      </div>
    </div>
  );
}
