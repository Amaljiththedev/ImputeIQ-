const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Data Shapes
 */
export interface Dataset {
  column_count?: number | null;
  id: string;
  filename: string;
  row_count: number;
  column_names: string[];
  numeric_columns: string[];
  categorical_columns: string[];
  uploaded_at: string;
}

export interface ColumnProfileOut {
  column: string;
  dtype: string;
  min: any;
  max: any;
  mean?: number | null;
  median?: number | null;
  std?: number | null;
  unique_count: number;
  null_count: number;
  zero_count: number;
  empty_string_count: number;
}

export interface PlaceholderCandidateOut {
  column: string;
  placeholder_value: any;
  count: number;
  placeholder: boolean;
  recommendation: string;
  confidence: number;
  reason: string;
  action: string;
  source?: string;
}

export interface ColumnAssumptionOut {
  column: string;
  assumed_meaning: string;
  plausible_range?: string | null;
  /** "user_dictionary" | "language_model" | "unavailable" */
  source: string;
  needs_review: boolean;
}

export interface ValidationProfileResponse {
  dataset_id: string;
  row_count: number;
  column_count: number;
  duplicate_count: number;
  profiles: ColumnProfileOut[];
  candidates: PlaceholderCandidateOut[];
  /** What the tool believes each column represents, and where that came from. */
  assumptions?: ColumnAssumptionOut[];
  has_data_dictionary?: boolean;
  /** Plain-language statement of how placeholders are detected. */
  detection_method?: string;
}

export interface DiagnosisResult {
  id: string;
  target_column: string;
  diagnosed_mechanism: "MAR" | "Ambiguous (MCAR/MNAR)" | string;
  diagnosis_detail: string;
  littles_p_value: number | null;
  littles_suggests_mcar: boolean | null;
  categorical_assoc_p_values: Record<string, number | null>;
  numeric_assoc_p_values: Record<string, number | null>;
  significant_drivers: string[];
  n_missing: number;
  recommended_method?: string | null;
  rationale?: string | null;
  available_methods?: string[] | null;
  is_cautious_default?: boolean;
  structural_zero_warning?: {
    flag: string;
    reason: string;
    name_pattern_match?: boolean;
  } | null;
  semantic_role?: string | null;
}

export interface ImputationResult {
  id: string;
  target_column: string;
  routed_mechanism: string;
  method_used: string;
  low_confidence: boolean;
  rationale: string;
  /** Cells actually filled, counted after imputation ran. */
  n_imputed: number;
  /** Cells deliberately left missing, with the reason. A column imputed within
   *  measurement strata has no donor for a stratum where nothing was observed. */
  n_unimputable?: number | null;
  unimputable_reason?: string | null;
  imputed_file_path: string;
  semantic_role?: string | null;
}

export interface ExplanationColumnResult {
  target_column: string;
  plain_language_summary: string;
  what_this_means_for_the_data: string;
  imputation_explanation: string;
  confidence_note: string;
  recommended_action: string;
}

export interface ExplanationResult {
  id: string;
  /** "language_model" when a provider wrote it, "template_fallback" when the
   *  deterministic local text was used instead. "gemini" appears only on rows
   *  stored before the provider seam existed. */
  generated_by: "language_model" | "template_fallback" | "gemini";
  overall_summary: string;
  columns_json: ExplanationColumnResult[];
}

export interface SensitivityMetric {
  column: string;
  type: "numeric" | "categorical" | string;
  missingCount: number;
  missingPct: number;
  stabilityScore: number;
  status: "Highly Stable" | "Robust" | "Needs Caution" | string;
  baselineVal: string;
  primaryVal: string;
  worstCaseVal: string;
  shiftPct: number;
  description: string;
  scenarioNotes: {
    mcar: string;
    mar: string;
    mnar: string;
  };
}

export interface DatasetResults {
  dataset: Dataset;
  diagnosis_results: DiagnosisResult[];
  imputation_results: ImputationResult[];
  explanation_results: ExplanationResult[];
  sensitivity_metrics?: SensitivityMetric[];
}

export interface MissingnessMatrix {
  columns: string[];       // column names with any missingness, empty if <2 affected columns
  matrix: number[][];      // symmetric correlation matrix, same order as `columns`, empty if <2 affected columns
  row_count: number;
}

export interface JobResponse {
  id: string;
  status: "pending" | "running" | "awaiting_approval" | "complete" | "completed" | "failed";
  current_phase?: "diagnosing" | "awaiting_approval" | "imputing" | "explaining" | "complete" | "error";
  error_message?: string | null;
  result?: unknown;
  error?: string;
}

/**
 * Dataset & Job Endpoints
 */
async function apiFetch(url: string, options: RequestInit = {}) {
  const res = await fetch(`${API_URL}${url}`, options);
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Request failed with status ${res.status}`);
  }
  return res.json();
}

export async function getDatasets(): Promise<Dataset[]> {
  return apiFetch("/api/datasets");
}

export async function uploadDataset(file: File): Promise<Dataset> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_URL}/api/datasets/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Upload failed with status ${res.status}`);
  }

  return res.json();
}

export async function startDiagnose(datasetId: string): Promise<JobResponse> {
  return apiFetch(`/api/datasets/${datasetId}/diagnose`, {
    method: "POST",
  });
}

export async function startRecommend(datasetId: string): Promise<JobResponse> {
  return apiFetch(`/api/datasets/${datasetId}/recommend`, {
    method: "POST",
  });
}

export async function getValidationProfile(datasetId: string): Promise<ValidationProfileResponse> {
  return apiFetch(`/api/datasets/${datasetId}/validate`);
}

/**
 * Attach a description of what the columns mean. Without one the tool infers a
 * variable's meaning from its name alone, which is unreliable when names are
 * abbreviated or misleading. Supplied descriptions take precedence.
 */
export async function setDataDictionary(datasetId: string, content: string): Promise<Dataset> {
  return apiFetch(`/api/datasets/${datasetId}/dictionary`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export async function applyValidation(
  datasetId: string,
  replacements: Array<{ column: string; placeholder_value: any }>,
  assumptionsReviewed = false
): Promise<JobResponse> {
  return apiFetch(`/api/datasets/${datasetId}/validate/apply`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ replacements, assumptions_reviewed: assumptionsReviewed }),
  });
}

export async function approveImputation(datasetId: string, methodOverrides: Record<string, string>): Promise<JobResponse> {
  return apiFetch(`/api/datasets/${datasetId}/impute/approve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ method_overrides: methodOverrides }),
  });
}

export async function clarifyRecommendation(datasetId: string, targetColumn: string, question: string): Promise<{ answer: string }> {
  return apiFetch(`/api/datasets/${datasetId}/recommend/clarify`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ target_column: targetColumn, question }),
  });
}

export async function startImpute(datasetId: string): Promise<JobResponse> {
  return apiFetch(`/api/datasets/${datasetId}/impute`, {
    method: "POST",
  });
}

export async function startExplain(datasetId: string): Promise<JobResponse> {
  return apiFetch(`/api/datasets/${datasetId}/explain`, {
    method: "POST",
  });
}

export async function getJobStatus(jobId: string): Promise<JobResponse> {
  return apiFetch(`/api/jobs/${jobId}`);
}

export async function startProcess(datasetId: string): Promise<JobResponse> {
  return apiFetch(`/api/datasets/${datasetId}/process`, {
    method: "POST",
  });
}

export async function getDatasetResults(datasetId: string): Promise<DatasetResults> {
  return apiFetch(`/api/datasets/${datasetId}/results`);
}

export async function getMissingnessMatrix(datasetId: string): Promise<MissingnessMatrix> {
  return apiFetch(`/api/datasets/${datasetId}/missingness-matrix`);
}

export async function downloadCleanedCsv(datasetId: string, filename = "cleaned_dataset.csv"): Promise<void> {
  const res = await fetch(`${API_URL}/api/datasets/${datasetId}/download`, {
    method: "GET",
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Download failed with status ${res.status}`);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const contentDisposition = res.headers.get("Content-Disposition");
  let outFilename = filename;
  if (contentDisposition && contentDisposition.includes("filename=")) {
    const parts = contentDisposition.split("filename=");
    if (parts[1]) {
      outFilename = parts[1].replace(/['"]/g, "").trim();
    }
  }
  a.download = outFilename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function fetchSensitivityMetrics(datasetId: string): Promise<SensitivityMetric[]> {
  return apiFetch(`/api/datasets/${datasetId}/sensitivity`);
}

/**
 * Robustness of an estimate to the missing-data assumption.
 *
 * Distinct from the sensitivity metrics, which describe what imputation did to
 * a column's distribution. This asks whether a result derived from the data
 * would change under a different imputation strategy, or under an assumed MNAR
 * departure. It requires no ground truth, so unlike the benchmark it works on
 * real data.
 */
export interface RobustnessStrategy {
  strategy: string;
  estimate: number;
  sd: number;
  n: number;
  shift_vs_complete_case_pct?: number;
  /** Unbiased under the diagnosed mechanism (van Buuren 2018, Table 1.1). */
  valid_under_mechanism?: boolean;
}

export interface RobustnessSweepPoint {
  delta_sd: number;
  estimate: number;
  shift_vs_observed_pct: number;
  /** The shift applies only to imputed cells, so its effect on the mean scales
   *  with how much is missing. This figure removes that, making columns with
   *  different missingness comparable. */
  shift_per_unit_missing_pct?: number;
  missing_fraction?: number;
  assumption: string;
}

export interface RobustnessColumn {
  column: string;
  diagnosed_mechanism: string;
  n_missing: number;
  strategies: RobustnessStrategy[];
  estimate_range?: [number, number] | null;
  spread_pct_of_estimate: number;
  /** Methods unbiased under this mechanism; the spread is measured over these. */
  valid_methods?: string[] | null;
  missing_fraction?: number;
  mnar_sweep: RobustnessSweepPoint[];
  robust_to_method_choice: boolean;
  interpretation: string;
}

export interface RobustnessReport {
  dataset_id: string;
  columns_analysed: number;
  method: string;
  columns: RobustnessColumn[];
}

export async function fetchRobustness(datasetId: string): Promise<RobustnessReport> {
  return apiFetch(`/api/datasets/${datasetId}/robustness`);
}
