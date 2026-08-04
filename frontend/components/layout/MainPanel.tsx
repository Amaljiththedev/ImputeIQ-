import { useAppSelector, useAppDispatch } from "@/store/hooks";
import { useEffect } from "react";
import { useSocket } from "@/lib/useSocket";
import UploadDropzone from "@/components/UploadDropzone";
import JobProgressTracker from "@/components/JobProgressTracker";
import OverviewTab from "@/components/tabs/OverviewTab";
import DiagnosisTab from "@/components/tabs/DiagnosisTab";
import ImputationTab from "@/components/tabs/ImputationTab";
import ExplanationTab from "@/components/tabs/ExplanationTab";
import SensitivityTab from "@/components/tabs/SensitivityTab";
import ApprovalScreen from "@/components/imputation/ApprovalScreen";
import ValidationGate from "@/components/validation/ValidationGate";
import { TabValue, setActiveTab, fetchResults } from "@/store/slices/datasetSlice";
import { AnimatePresence, motion } from "framer-motion";
import { UploadCloud, Sparkles } from "lucide-react";

const TABS: { value: TabValue; label: string }[] = [
  { value: "overview", label: "Overview" },
  { value: "diagnosis", label: "Diagnosis" },
  { value: "imputation", label: "Imputation" },
  { value: "explanation", label: "Explanation" },
  { value: "sensitivity", label: "Sensitivity Analysis" },
];

const EASE = [0.22, 1, 0.36, 1] as const;

function formatUploadDate(value?: string | number | Date) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export default function MainPanel() {
  const { datasets, activeDatasetId, activeResults, activeTab = "overview" } = useAppSelector((s) => s.dataset);
  const { phase, currentJobId } = useAppSelector((s) => s.job);
  const dispatch = useAppDispatch();

  useSocket(currentJobId, activeDatasetId);

  const activeDataset = datasets.find((d) => d.id === activeDatasetId);

  const isProcessing = phase !== "idle" && phase !== "complete" && phase !== "error" && phase !== "awaiting_approval" && phase !== "validating";

  useEffect(() => {
    if (activeDatasetId && !activeResults && !isProcessing && phase !== "error" && phase !== "awaiting_approval" && phase !== "validating") {
      dispatch(fetchResults(activeDatasetId));
    }
  }, [activeDatasetId, activeResults, isProcessing, phase, dispatch]);

  // 1. Empty state
  if (!activeDataset) {
    return (
      <main className="flex-1 h-full flex flex-col">
        <div className="flex-1 flex flex-col items-center justify-center px-8">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: EASE }}
            className="w-full max-w-md"
          >
            <div className="glass rounded-3xl px-10 py-12 flex flex-col items-center text-center">
              <div className="w-14 h-14 rounded-xl glass-thin flex items-center justify-center mb-6">
                <UploadCloud className="w-6 h-6 text-gray-500" strokeWidth={1.5} />
              </div>
              <h2 className="text-[28px] font-semibold text-gray-900 mb-2">
                New analysis
              </h2>
              <p className="text-[15px] text-gray-600 leading-relaxed mb-8 max-w-xs">
                Upload a dataset to begin intelligent missing data analysis.
              </p>
              <div className="w-full">
                <UploadDropzone />
              </div>
            </div>
          </motion.div>
        </div>
      </main>
    );
  }

  // 2. Awaiting approval state
  if (phase === "awaiting_approval") {
    return (
      <main className="flex-1 h-full flex flex-col overflow-y-auto">
        <ApprovalScreen />
      </main>
    );
  }

  // 2.5. Validating state (Preprocessing & Placeholder check)
  if (phase === "validating") {
    return (
      <main className="flex-1 h-full flex flex-col overflow-y-auto p-8">
        <ValidationGate />
      </main>
    );
  }

  // 3. Processing state
  if (isProcessing || !activeResults) {
    return (
      <main className="flex-1 h-full flex flex-col">
        <div className="shrink-0 px-8 pt-8 pb-2">
          <h2 className="text-[28px] font-semibold text-gray-900">
            {activeDataset.filename}
          </h2>
          <p className="text-[13px] text-gray-600 mt-1 tabular-nums">
            {activeDataset.row_count.toLocaleString()} rows
          </p>
        </div>

        <div className="flex-1 flex items-center justify-center px-8">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: EASE }}
            className="w-full max-w-lg"
          >
            <div className="glass relative rounded-3xl px-10 py-12 overflow-hidden">
              <motion.div
                aria-hidden
                className="absolute -top-16 -right-16 w-48 h-48 rounded-full bg-blue-500/[0.07]"
                animate={{ scale: [1, 1.15, 1], opacity: [0.5, 0.9, 0.5] }}
                transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
              />
              <div className="relative flex flex-col items-center text-center">
                <div className="w-12 h-12 rounded-xl bg-blue-500/10 flex items-center justify-center mb-6">
                  <Sparkles className="w-5 h-5 text-blue-500" strokeWidth={1.5} />
                </div>
                <h3 className="text-[17px] font-semibold text-gray-900 mb-1">
                  Analysing your dataset
                </h3>
                <p className="text-[13px] text-gray-600 mb-8">
                  This usually takes a moment. Feel free to wait here.
                </p>
                <div className="w-full">
                  <JobProgressTracker />
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </main>
    );
  }

  // 3. Results state
  return (
    <main className="flex-1 h-full min-h-0 flex flex-col overflow-hidden">
      <header className="shrink-0 px-8 pt-8 pb-6">
        <div className="max-w-7xl mx-auto w-full">
          <div className="flex items-start justify-between gap-6 mb-6">
            <div>
              <h2 className="text-[28px] font-semibold text-gray-900">
                {activeDataset.filename}
              </h2>
              <p className="text-[13px] text-gray-600 mt-1.5 tabular-nums">
                {activeDataset.row_count.toLocaleString()} rows
                {(activeDataset.column_count ?? activeDataset.column_names?.length) != null && (
                  <span> &middot; {(activeDataset.column_count ?? activeDataset.column_names.length).toLocaleString()} columns</span>
                )}
                {formatUploadDate(activeDataset.uploaded_at) && (
                  <span> &middot; Uploaded {formatUploadDate(activeDataset.uploaded_at)}</span>
                )}
              </p>
            </div>
          </div>

          <nav className="iq-segmented inline-flex items-center relative">
            {TABS.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => dispatch(setActiveTab(value))}
                className={`relative px-4 py-1.5 text-[13px] rounded-full transition-colors duration-300 ${
                  activeTab === value
                    ? "text-gray-900 font-semibold"
                    : "text-gray-600 hover:text-gray-900"
                }`}
              >
                {activeTab === value && (
                  <motion.span
                    layoutId="active-tab-pill"
                    className="iq-segment-active absolute inset-0 rounded-full"
                    transition={{ duration: 0.3, ease: EASE }}
                  />
                )}
                <span className="relative z-10">{label}</span>
              </button>
            ))}
          </nav>
        </div>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto px-8 pb-8">
        <div className="max-w-7xl mx-auto w-full h-full">
          <div className="glass rounded-3xl h-full min-h-0 flex flex-col overflow-hidden">
            <AnimatePresence mode="wait">
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.25, ease: EASE }}
                className="flex-1 min-h-0 flex flex-col overflow-y-auto px-8 py-8"
              >
                {activeTab === "overview" && <OverviewTab />}
                {activeTab === "diagnosis" && <DiagnosisTab />}
                {activeTab === "imputation" && <ImputationTab />}
                {activeTab === "explanation" && <ExplanationTab />}
                {activeTab === "sensitivity" && <SensitivityTab />}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </main>
  );
}