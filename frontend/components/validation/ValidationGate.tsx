"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Info,
  Loader2,
  Sparkles,
  Table as TableIcon,
} from "lucide-react";
import {
  applyValidation,
  getValidationProfile,
  setDataDictionary,
  ColumnAssumptionOut,
  PlaceholderCandidateOut,
  ValidationProfileResponse,
} from "@/lib/api";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setCurrentJobId, setPhase, addLog } from "@/store/slices/jobSlice";

function reprValue(val: unknown): string {
  if (val === null || val === undefined) return "null";
  if (typeof val === "string" && val.trim() === "") return '"" (empty string)';
  return String(val);
}

/** Where a column's stated meaning came from. */
function SourceBadge({ source }: { source: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    user_dictionary: { label: "Your description", cls: "bg-success-bg text-success-fg" },
    language_model: { label: "Inferred from name", cls: "bg-warning-bg text-warning-fg" },
    unavailable: { label: "Not established", cls: "bg-gray-100 text-gray-600" },
  };
  const { label, cls } = map[source] ?? map.unavailable;
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium ${cls}`}>
      {label}
    </span>
  );
}

export default function ValidationGate() {
  const dispatch = useAppDispatch();
  const activeDatasetId = useAppSelector((state) => state.dataset.activeDatasetId);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [profileData, setProfileData] = useState<ValidationProfileResponse | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const [showStatsTable, setShowStatsTable] = useState(false);

  // Data dictionary
  const [showDictionary, setShowDictionary] = useState(false);
  const [dictionaryText, setDictionaryText] = useState("");
  const [savingDictionary, setSavingDictionary] = useState(false);

  // Assumptions must be acknowledged before anything is written, since every
  // placeholder decision below depends on them being right.
  const [assumptionsReviewed, setAssumptionsReviewed] = useState(false);

  async function loadProfile(datasetId: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await getValidationProfile(datasetId);
      setProfileData(data);
      const initial: Record<string, boolean> = {};
      data.candidates.forEach((cand) => {
        const key = `${cand.column}:${cand.placeholder_value}`;
        initial[key] =
          cand.action === "replace_with_nan" ||
          cand.recommendation.toLowerCase().includes("convert");
      });
      setSelected(initial);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load dataset validation profile.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!activeDatasetId) return;
    loadProfile(activeDatasetId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDatasetId]);

  const handleSaveDictionary = async () => {
    if (!activeDatasetId) return;
    setSavingDictionary(true);
    try {
      await setDataDictionary(activeDatasetId, dictionaryText);
      // Re-profile: descriptions change how placeholder candidates are judged.
      setAssumptionsReviewed(false);
      await loadProfile(activeDatasetId);
      setShowDictionary(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save data dictionary.");
    } finally {
      setSavingDictionary(false);
    }
  };

  const handleToggleCandidate = (candidate: PlaceholderCandidateOut) => {
    const key = `${candidate.column}:${candidate.placeholder_value}`;
    setSelected((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleApplyChanges = async (applySelected: boolean) => {
    if (!activeDatasetId) return;
    setSubmitting(true);
    try {
      const replacements: Array<{ column: string; placeholder_value: unknown }> = [];
      if (applySelected && profileData) {
        profileData.candidates.forEach((cand) => {
          const key = `${cand.column}:${cand.placeholder_value}`;
          if (selected[key]) {
            replacements.push({ column: cand.column, placeholder_value: cand.placeholder_value });
          }
        });
      }

      const job = await applyValidation(activeDatasetId, replacements, assumptionsReviewed);
      dispatch(setCurrentJobId(job.id));
      dispatch(setPhase("diagnosing"));
      dispatch(
        addLog(
          replacements.length > 0
            ? `Applied ${replacements.length} placeholder conversion(s) to a copy (` +
                replacements.map((r) => `${r.column}=${r.placeholder_value}`).join(", ") +
                "). Starting diagnosis…"
            : "Proceeding with original values, no conversions applied. Starting diagnosis…"
        )
      );
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to apply validation settings.");
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="glass rounded-3xl flex flex-col items-center justify-center p-16 min-h-[380px] text-center">
        <Loader2 className="w-7 h-7 text-blue-500 animate-spin mb-4" strokeWidth={1.75} />
        <h3 className="text-[17px] font-semibold text-gray-900">Profiling the dataset</h3>
        <p className="text-[13px] text-gray-600 mt-1.5 max-w-md">
          Reading distributions and null counts, then checking which suspicious values are
          plausible for each column.
        </p>
      </div>
    );
  }

  if (error || !profileData) {
    return (
      <div className="glass rounded-3xl p-10 flex flex-col items-center text-center">
        <AlertTriangle className="w-7 h-7 text-danger-fg mb-3" strokeWidth={1.75} />
        <h3 className="text-[17px] font-semibold text-gray-900">Profiling failed</h3>
        <p className="text-[13px] text-gray-600 mt-1.5 max-w-md">
          {error || "No validation data received."}
        </p>
        <button
          onClick={() => handleApplyChanges(false)}
          className="mt-6 px-5 py-2.5 rounded-full bg-blue-500 hover:bg-blue-600 text-white text-[13px] font-medium transition-colors"
        >
          Continue without conversions
        </button>
      </div>
    );
  }

  const assumptions: ColumnAssumptionOut[] = profileData.assumptions ?? [];
  const needingReview = assumptions.filter((a) => a.needs_review);
  const blocked = needingReview.length > 0 && !assumptionsReviewed;

  return (
    <div className="space-y-6 max-w-6xl mx-auto pb-12">
      <header>
        <h1 className="text-[28px] font-semibold text-gray-900">Check the data before it changes</h1>
        <p className="text-[15px] text-gray-600 mt-1.5 max-w-3xl leading-relaxed">
          Some datasets record missing values as real ones, such as a zero blood pressure or{" "}
          <code className="font-mono text-[13px]">-999</code>. Nothing is altered until you approve
          it, and your original file is never modified.
        </p>
      </header>

      {/* How detection works. Stated rather than left to be inferred, because
          the judgement rests on the column name unless the user says otherwise. */}
      {profileData.detection_method && (
        <div className="glass-thin rounded-xl px-5 py-4 flex gap-3">
          <Info className="w-4 h-4 text-gray-500 shrink-0 mt-0.5" strokeWidth={1.75} />
          <div>
            <p className="text-[13px] font-semibold text-gray-900 mb-1">How these values were identified</p>
            <p className="text-[13px] text-gray-600 leading-relaxed">{profileData.detection_method}</p>
          </div>
        </div>
      )}

      {/* Column meanings. This is the interpretation everything below depends on. */}
      <section className="glass rounded-3xl overflow-hidden">
        <div className="px-6 py-5 border-b border-black/[0.06] flex items-start justify-between gap-4">
          <div>
            <h2 className="text-[17px] font-semibold text-gray-900">What each column is taken to mean</h2>
            <p className="text-[13px] text-gray-600 mt-1 max-w-2xl leading-relaxed">
              Placeholder decisions follow from these readings. Anything marked{" "}
              <span className="font-medium text-warning-fg">inferred from name</span> is a guess and
              may be wrong. Correct it by describing your data.
            </p>
          </div>
          <button
            onClick={() => setShowDictionary((v) => !v)}
            className="shrink-0 inline-flex items-center gap-2 rounded-full border border-blue-500/30 px-4 py-2 text-[13px] font-medium text-blue-500 hover:bg-blue-50 transition-colors"
          >
            <BookOpen className="w-4 h-4" strokeWidth={1.75} />
            {profileData.has_data_dictionary ? "Edit description" : "Describe your data"}
          </button>
        </div>

        {showDictionary && (
          <div className="px-6 py-5 border-b border-black/[0.06] bg-white/40">
            <label className="block text-[13px] font-medium text-gray-900 mb-2">
              Describe your columns
            </label>
            <p className="text-[12px] text-gray-600 mb-3 leading-relaxed">
              One per line as <code className="font-mono">column: meaning</code>, or paste JSON. Any
              column you describe here overrides the tool&apos;s own reading of its name.
            </p>
            <textarea
              value={dictionaryText}
              onChange={(e) => setDictionaryText(e.target.value)}
              rows={7}
              spellCheck={false}
              placeholder={"bmi: Body mass index in kg/m2\nweight: Survey sampling weight, 0-1, not body weight\nn_visits: Prior clinic visits; missing means none occurred"}
              className="w-full rounded-xl border border-gray-300 bg-white px-4 py-3 font-mono text-[12px] text-gray-900 leading-relaxed focus:outline-none focus:border-blue-500"
            />
            <div className="flex items-center gap-3 mt-3">
              <button
                onClick={handleSaveDictionary}
                disabled={savingDictionary || !dictionaryText.trim()}
                className="inline-flex items-center gap-2 rounded-full bg-blue-500 hover:bg-blue-600 disabled:opacity-40 px-5 py-2 text-[13px] font-medium text-white transition-colors"
              >
                {savingDictionary && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {savingDictionary ? "Saving and re-checking…" : "Save and re-check"}
              </button>
              <button
                onClick={() => setShowDictionary(false)}
                className="text-[13px] text-gray-600 hover:text-gray-900 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        <div className="divide-y divide-black/[0.05]">
          {assumptions.map((a) => (
            <div key={a.column} className="px-6 py-3.5 flex items-start gap-4">
              <code className="font-mono text-[13px] font-medium text-gray-900 w-44 shrink-0 truncate">
                {a.column}
              </code>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] text-gray-700 leading-relaxed">{a.assumed_meaning}</p>
                {a.plausible_range && (
                  <p className="text-[12px] text-gray-500 mt-0.5">
                    Expected range: {a.plausible_range}
                  </p>
                )}
              </div>
              <SourceBadge source={a.source} />
            </div>
          ))}
          {assumptions.length === 0 && (
            <p className="px-6 py-5 text-[13px] text-gray-600">No column assumptions returned.</p>
          )}
        </div>

        {needingReview.length > 0 && (
          <label className="flex items-start gap-3 px-6 py-4 border-t border-black/[0.06] bg-warning-bg/40 cursor-pointer">
            <input
              type="checkbox"
              checked={assumptionsReviewed}
              onChange={(e) => setAssumptionsReviewed(e.target.checked)}
              className="mt-0.5 w-4 h-4 accent-blue-500 cursor-pointer"
            />
            <span className="text-[13px] text-gray-900 leading-relaxed">
              I have read the {needingReview.length} inferred{" "}
              {needingReview.length === 1 ? "meaning" : "meanings"} above and they are correct for my
              data.
            </span>
          </label>
        )}
      </section>

      {/* Placeholder candidates */}
      <section className="glass rounded-3xl overflow-hidden">
        <div className="px-6 py-5 border-b border-black/[0.06]">
          <h2 className="text-[17px] font-semibold text-gray-900">Values that may mean missing</h2>
          <p className="text-[13px] text-gray-600 mt-1 leading-relaxed">
            Tick the ones to convert to <code className="font-mono text-[12px]">NaN</code> on a
            working copy. {profileData.candidates.length} candidate
            {profileData.candidates.length === 1 ? "" : "s"} found across{" "}
            {profileData.row_count.toLocaleString()} rows.
          </p>
        </div>

        {profileData.candidates.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <CheckCircle2 className="w-6 h-6 text-success mx-auto mb-2" strokeWidth={1.75} />
            <p className="text-[13px] font-medium text-gray-900">No suspicious values found</p>
            <p className="text-[12px] text-gray-600 mt-0.5">
              Every column uses standard null representation.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-black/[0.05]">
            {profileData.candidates.map((cand, idx) => {
              const key = `${cand.column}:${cand.placeholder_value}`;
              const isChecked = !!selected[key];
              const pct = ((cand.count / profileData.row_count) * 100).toFixed(1);
              return (
                <label
                  key={idx}
                  className={`flex items-start gap-4 px-6 py-4 cursor-pointer transition-colors ${
                    isChecked ? "bg-blue-500/[0.04]" : "hover:bg-white/50"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => handleToggleCandidate(cand)}
                    className="mt-1 w-4 h-4 accent-blue-500 cursor-pointer shrink-0"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2.5 flex-wrap mb-1">
                      <code className="font-mono text-[13px] font-medium text-gray-900">
                        {cand.column}
                      </code>
                      <span className="font-mono text-[12px] rounded-md bg-warning-bg px-2 py-0.5 text-warning-fg">
                        {reprValue(cand.placeholder_value)}
                      </span>
                      <span className="text-[12px] text-gray-500 tabular-nums">
                        {cand.count.toLocaleString()} rows ({pct}%)
                      </span>
                      {cand.source && (
                        <span className="inline-flex items-center gap-1 text-[11px] font-medium text-gray-500">
                          <Sparkles className="w-3 h-3" strokeWidth={2} />
                          {cand.source === "gemini" ? "model" : "rule"} ·{" "}
                          {(cand.confidence * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
                    <p className="text-[13px] text-gray-600 leading-relaxed">{cand.reason}</p>
                  </div>
                </label>
              );
            })}
          </div>
        )}
      </section>

      {/* Column statistics */}
      <section className="glass rounded-3xl overflow-hidden">
        <button
          onClick={() => setShowStatsTable((v) => !v)}
          className="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-white/50 transition-colors"
        >
          <span className="flex items-center gap-2.5 text-[13px] font-semibold text-gray-900">
            <TableIcon className="w-4 h-4 text-gray-500" strokeWidth={1.75} />
            Column statistics
            <span className="font-normal text-gray-500">
              ({profileData.profiles.length} columns)
            </span>
          </span>
          {showStatsTable ? (
            <ChevronUp className="w-4 h-4 text-gray-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-gray-400" />
          )}
        </button>

        {showStatsTable && (
          <div className="border-t border-black/[0.06] overflow-x-auto">
            <table className="w-full text-left text-[12px]">
              <thead>
                <tr className="text-gray-500 border-b border-black/[0.06]">
                  {["Column", "Type", "Min", "Max", "Mean", "Median", "SD", "Unique", "Nulls", "Zeros"].map(
                    (h, i) => (
                      <th
                        key={h}
                        className={`py-2.5 px-4 font-medium ${i > 1 ? "text-right" : ""}`}
                      >
                        {h}
                      </th>
                    )
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-black/[0.04]">
                {profileData.profiles.map((p, idx) => (
                  <tr key={idx} className="hover:bg-white/50">
                    <td className="py-2.5 px-4 font-mono font-medium text-gray-900">{p.column}</td>
                    <td className="py-2.5 px-4 font-mono text-gray-500">{p.dtype}</td>
                    <td className="py-2.5 px-4 text-right font-mono tabular-nums">{p.min ?? "—"}</td>
                    <td className="py-2.5 px-4 text-right font-mono tabular-nums">{p.max ?? "—"}</td>
                    <td className="py-2.5 px-4 text-right font-mono tabular-nums">{p.mean ?? "—"}</td>
                    <td className="py-2.5 px-4 text-right font-mono tabular-nums">{p.median ?? "—"}</td>
                    <td className="py-2.5 px-4 text-right font-mono tabular-nums">{p.std ?? "—"}</td>
                    <td className="py-2.5 px-4 text-right tabular-nums">{p.unique_count}</td>
                    <td
                      className={`py-2.5 px-4 text-right tabular-nums ${
                        p.null_count > 0 ? "text-warning-fg font-medium" : ""
                      }`}
                    >
                      {p.null_count}
                    </td>
                    <td
                      className={`py-2.5 px-4 text-right tabular-nums ${
                        p.zero_count > 0 ? "text-blue-500 font-medium" : ""
                      }`}
                    >
                      {p.zero_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <p className="text-[12px] text-gray-500 max-w-md leading-relaxed">
          Conversions are written to a copy. Your uploaded file is never modified.
        </p>
        <div className="flex items-center gap-3 w-full sm:w-auto">
          <button
            onClick={() => handleApplyChanges(false)}
            disabled={submitting}
            className="flex-1 sm:flex-initial rounded-full border border-gray-300 px-5 py-2.5 text-[13px] font-medium text-gray-700 hover:bg-white/70 transition-colors disabled:opacity-40"
          >
            Keep original values
          </button>
          <button
            onClick={() => handleApplyChanges(true)}
            disabled={submitting || blocked}
            title={blocked ? "Confirm the inferred column meanings first" : undefined}
            className="flex-1 sm:flex-initial inline-flex items-center justify-center gap-2 rounded-full bg-blue-500 hover:bg-blue-600 px-6 py-2.5 text-[13px] font-medium text-white transition-colors disabled:opacity-40"
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            {submitting ? "Applying…" : "Apply and run diagnosis"}
          </button>
        </div>
      </div>

      {blocked && (
        <p className="text-[12px] text-warning-fg text-right">
          Confirm the inferred column meanings before applying changes.
        </p>
      )}
    </div>
  );
}
