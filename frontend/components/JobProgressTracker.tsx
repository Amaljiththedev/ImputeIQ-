import { useAppSelector } from "@/store/hooks";
import { CheckCircle2, Loader2, Circle, AlertCircle } from "lucide-react";

export default function JobProgressTracker() {
  const { phase, error, logs } = useAppSelector((s) => s.job);

  const steps = [
    { id: "diagnosing", label: "Diagnosing missing data patterns", desc: "Scanning columns for gaps and patterns" },
    { id: "imputing", label: "Filling in missing values", desc: "Applying the best-fit imputation strategy" },
    { id: "explaining", label: "Preparing explanation", desc: "Generating a plain-language summary" },
    { id: "complete", label: "Loading dashboard results", desc: "Finalizing your dataset overview" },
  ];

  const getCurrentStepIndex = () => {
    if (phase === "idle") return -1;
    if (phase === "complete") return 3;
    return steps.findIndex((s) => s.id === phase);
  };

  const currentIndex = getCurrentStepIndex();
  const progressPercent = Math.max(0, Math.min(100, ((currentIndex + 1) / steps.length) * 100));

  // Get the latest log message to show under the active step
  const latestLog = logs.length > 0 ? logs[logs.length - 1] : null;

  if (phase === "error") {
    return (
      <div className="max-w-md w-full p-7 bg-white rounded-2xl border border-red-100 shadow-sm flex flex-col items-center text-center">
        <div className="w-14 h-14 rounded-full bg-red-50 flex items-center justify-center mb-4">
          <AlertCircle className="w-7 h-7 text-red-500" strokeWidth={1.75} />
        </div>
        <h3 className="text-[16px] font-semibold text-gray-900 mb-1.5">Processing Failed</h3>
        <p className="text-[13.5px] text-gray-500 leading-relaxed">
          {error || "An unknown error occurred during processing."}
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-md w-full bg-white rounded-2xl border border-gray-200 shadow-sm p-7">
      <div className="flex items-center justify-between mb-7">
        <span className="text-[13px] font-medium text-gray-500">Processing dataset</span>
        <span className="text-[13px] font-semibold text-blue-500 tabular-nums">
          {Math.round(progressPercent)}%
        </span>
      </div>

      <div className="relative">
        {steps.map((step, index) => {
          const isComplete = currentIndex > index;
          const isCurrent = currentIndex === index;
          const isLast = index === steps.length - 1;

          return (
            <div key={step.id} className="relative flex gap-4 pb-8 last:pb-0">
              {!isLast && (
                <div className="absolute left-[11px] top-6 w-[2px] h-[calc(100%-8px)] bg-gray-200 overflow-hidden rounded-full">
                  <div
                    className={`w-full bg-blue-500 rounded-full transition-all duration-700 ease-out ${
                      isComplete ? "h-full" : "h-0"
                    }`}
                  />
                </div>
              )}

              <div className="relative shrink-0 z-10">
                {isComplete ? (
                  <div className="w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center">
                    <CheckCircle2 className="w-4 h-4 text-white" strokeWidth={2.5} fill="none" />
                  </div>
                ) : isCurrent ? (
                  <div className="relative w-6 h-6 flex items-center justify-center">
                    <span className="absolute inset-0 rounded-full bg-blue-500/15 animate-ping" />
                    <Loader2 className="w-5 h-5 text-blue-500 animate-spin relative" strokeWidth={2} />
                  </div>
                ) : (
                  <Circle className="w-6 h-6 text-gray-300" strokeWidth={1.5} />
                )}
              </div>

              <div className={`pt-0.5 transition-opacity duration-500 ${
                isCurrent ? "opacity-100" : isComplete ? "opacity-70" : "opacity-40"
              }`}>
                <div className={`text-[14.5px] font-medium leading-none ${
                  isCurrent ? "text-gray-900" : isComplete ? "text-gray-700" : "text-gray-400"
                }`}>
                  {step.label}
                </div>
                <div className="text-[12.5px] text-gray-400 mt-1">
                  {step.desc}
                </div>

                {/* Live log message — only show under the active step */}
                {isCurrent && latestLog && (
                  <div className="mt-2 text-[11.5px] text-blue-500/70 font-mono truncate max-w-[280px] animate-pulse">
                    → {latestLog}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}