"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, AlertTriangle, Loader2 } from "lucide-react";
import { useAppSelector } from "@/store/hooks";

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

interface ColumnRecommendation {
  columnName: string;
  mechanism: "MAR" | "Uncertain";
  recommendedMethod: "Median" | "Mean" | "KNN" | "MICE" | "Regression";
  isCautiousDefault: boolean;
  rationale: string;
  availableMethods: string[];
}

const mockRecommendations: ColumnRecommendation[] = [
  {
    columnName: "glucose",
    mechanism: "MAR",
    recommendedMethod: "Median",
    isCautiousDefault: false,
    rationale:
      "This performed best in our testing for this type of pattern (18.3% average error, versus 18.4 to 21.6% for other methods), and stays reliable even as more values go missing.",
    availableMethods: ["Median", "Mean", "KNN", "MICE", "Regression"],
  },
  {
    columnName: "systolic_bp",
    mechanism: "Uncertain",
    recommendedMethod: "Median",
    isCautiousDefault: true,
    rationale:
      "We couldn't determine why these values are missing, so we default to the safest option rather than risk a wrong guess. If you have context on this, let us know on the previous step.",
    availableMethods: ["Median", "Mean", "KNN", "MICE", "Regression"],
  },
];

const exampleQuestions: Record<string, string> = {
  glucose: "Why not use KNN if the missing rate is low?",
  systolic_bp: "These readings were from a faulty sensor — does that change anything?",
};

const mockClarifications: Record<string, string> = {
  glucose:
    "Good question. KNN would also work well here (18.4% error), but median is slightly more resilient when the missing rate exceeds ~15%. Since your dataset is at 18.3% missing for this column, median gives a more stable result across repeated runs.",
  systolic_bp:
    "That's helpful context. If the sensor was faulty, the values are likely missing completely at random (MCAR), which means simpler methods like median or mean imputation are both appropriate. Median remains the safest default since it's robust to outliers that faulty sensors sometimes introduce.",
};

/* ------------------------------------------------------------------ */
/*  Column card component                                              */
/* ------------------------------------------------------------------ */

function ColumnCard({
  rec,
  selectedMethod,
  onMethodChange,
}: {
  rec: ColumnRecommendation;
  selectedMethod: string;
  onMethodChange: (method: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [clarification, setClarification] = useState<string | null>(null);
  const [isAsking, setIsAsking] = useState(false);

  const handleAsk = () => {
    if (!question.trim()) return;
    setIsAsking(true);

    // TODO: replace with real POST /datasets/{id}/recommend/clarify call
    setTimeout(() => {
      setClarification(
        mockClarifications[rec.columnName] ??
          "Based on the data characteristics, the current recommendation remains the best option for this column. The chosen method balances accuracy and robustness for the observed missingness pattern."
      );
      setIsAsking(false);
    }, 1200);
  };

  return (
    <div className="rounded-xl border border-gray-200/80 bg-white px-5 py-5 space-y-4">
      {/* Header row: column name + status pill */}
      <div className="flex items-center justify-between">
        <span className="text-[15px] font-medium text-gray-900 font-mono">
          {rec.columnName}
        </span>
        {rec.mechanism === "MAR" ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200/60">
            MAR
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700 ring-1 ring-amber-200/60">
            <AlertTriangle className="w-3 h-3" />
            Uncertain
          </span>
        )}
      </div>

      {/* Recommended method */}
      <div>
        <p className="text-xs text-gray-400 mb-0.5">Recommended</p>
        <p className="text-[14px] text-gray-900 font-medium">
          {rec.recommendedMethod}
          {rec.isCautiousDefault && (
            <span className="font-normal text-gray-400">
              {" "}
              — cautious default
            </span>
          )}
        </p>
      </div>

      {/* Rationale */}
      <p className="text-[13px] text-gray-500 leading-relaxed">
        {rec.rationale}
      </p>

      {/* Method select */}
      <div>
        <label
          htmlFor={`method-${rec.columnName}`}
          className="block text-xs text-gray-400 mb-1.5"
        >
          Method to use
        </label>
        <select
          id={`method-${rec.columnName}`}
          value={selectedMethod}
          onChange={(e) => onMethodChange(e.target.value)}
          className="w-full appearance-none rounded-lg border border-gray-200 bg-gray-50/60 px-3 py-2 text-[14px] text-gray-900 outline-none transition-colors focus:border-gray-400 focus:bg-white"
        >
          {rec.availableMethods.map((m) => (
            <option key={m} value={m}>
              {m}
              {m === rec.recommendedMethod ? " (recommended)" : ""}
            </option>
          ))}
        </select>
      </div>

      {/* Ask a question */}
      <div>
        <label
          htmlFor={`question-${rec.columnName}`}
          className="block text-xs text-gray-400 mb-1.5"
        >
          Ask a question about this recommendation
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
            placeholder={exampleQuestions[rec.columnName] ?? "Ask anything…"}
            className="flex-1 rounded-lg border border-gray-200 bg-gray-50/60 px-3 py-2 text-[14px] text-gray-900 placeholder:text-gray-300 outline-none transition-colors focus:border-gray-400 focus:bg-white"
          />
          <button
            onClick={handleAsk}
            disabled={isAsking || !question.trim()}
            className="shrink-0 rounded-lg border border-gray-200 bg-white px-3.5 py-2 text-[13px] font-medium text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {isAsking ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              "Ask"
            )}
          </button>
        </div>

        {/* Clarification response */}
        {clarification && (
          <div className="mt-3 rounded-lg bg-gray-50 border border-gray-100 px-4 py-3 text-[13px] text-gray-600 leading-relaxed animate-in fade-in slide-in-from-top-1 duration-300">
            <p className="text-xs text-gray-400 mb-1">Assistant</p>
            {clarification}
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page component                                                     */
/* ------------------------------------------------------------------ */

export default function ApprovePage() {
  const router = useRouter();
  const { activeResults } = useAppSelector((s) => s.dataset);

  const derivedRecommendations: ColumnRecommendation[] = activeResults?.imputation_results?.length
    ? activeResults.imputation_results.map((imp) => {
        const diag = activeResults.diagnosis_results.find((d) => d.target_column === imp.target_column);
        return {
          columnName: imp.target_column,
          mechanism: diag?.diagnosed_mechanism?.includes("MAR") ? "MAR" : "Uncertain",
          recommendedMethod: (imp.method_used as any) || "Median",
          isCautiousDefault: imp.low_confidence,
          rationale: imp.rationale || "Recommended based on missingness patterns.",
          availableMethods: ["Median", "Mean", "KNN", "MICE", "Regression"],
        };
      })
    : mockRecommendations;

  // Local state: selected method per column
  const [selections, setSelections] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      derivedRecommendations.map((r) => [r.columnName, r.recommendedMethod])
    )
  );

  const handleMethodChange = (columnName: string, method: string) => {
    setSelections((prev) => ({ ...prev, [columnName]: method }));
  };

  const handleContinue = () => {
    console.log("Approved methods:", selections);
    router.push("/");
  };

  const handleCancel = () => {
    router.back();
  };

  return (
    <div className="min-h-screen bg-white">
      <div className="mx-auto max-w-2xl px-6 py-10 md:py-16">
        {/* Breadcrumb */}
        <button
          onClick={() => router.back()}
          className="inline-flex items-center gap-1.5 text-[13px] text-gray-400 hover:text-gray-600 transition-colors mb-8"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to diagnosis
        </button>

        {/* Heading */}
        <div className="mb-10">
          <h1 className="text-2xl font-medium text-gray-900 tracking-tight mb-1.5">
            Before we fill in the gaps
          </h1>
          <p className="text-[15px] text-gray-400">
            Review our recommendation for each column, or choose your own.
          </p>
        </div>

        {/* Column cards */}
        <div className="space-y-4 mb-12">
          {derivedRecommendations.map((rec) => (
            <ColumnCard
              key={rec.columnName}
              rec={rec}
              selectedMethod={selections[rec.columnName]}
              onMethodChange={(method) =>
                handleMethodChange(rec.columnName, method)
              }
            />
          ))}
        </div>

        {/* Action buttons */}
        <div className="flex items-center justify-end gap-3">
          <button
            onClick={handleCancel}
            className="rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-[14px] font-medium text-gray-600 transition-colors hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleContinue}
            className="rounded-lg bg-gray-900 px-5 py-2.5 text-[14px] font-medium text-white transition-colors hover:bg-gray-800"
          >
            Use these methods and continue
          </button>
        </div>
      </div>
    </div>
  );
}
