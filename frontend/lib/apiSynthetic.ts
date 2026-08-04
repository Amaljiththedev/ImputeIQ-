import { Dataset } from "./api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ColumnSpec {
  mechanism: "MCAR" | "MAR" | "MNAR" | "none";
  target_missing_rate?: number;
  actual_missing_rate?: number;
  driver_column?: string | null;
  rule?: string;
  output_file?: string;
}

export interface GeneratedFileRecord {
  mechanism: string;
  target_column: string;
  driver_column?: string | null;
  requested_rate: number;
  actual_missing_count: number;
  actual_missing_pct: number;
  output_file: string;
  unchanged_elsewhere?: boolean;
}

export interface SyntheticManifest {
  seed: number;
  source: string;
  n_rows: number;
  columns: Record<string, ColumnSpec>;
  generated_files: GeneratedFileRecord[];
}

export interface BenchmarkScorecardItem {
  target_column: string;
  ground_truth_mechanism: string;
  ground_truth_driver?: string | null;
  ground_truth_rate?: number;
  ground_truth_rule?: string;
  diagnosed_mechanism?: string | null;
  recommended_method?: string | null;
  littles_p_value?: number | null;
  significant_drivers: string[];
  is_match: boolean;
  match_status: string;
  rationale?: string | null;
}

export interface BenchmarkScorecardResponse {
  dataset_id: string;
  dataset_filename: string;
  is_benchmark_dataset: boolean;
  source_dataset: string;
  total_columns_evaluated: number;
  correct_mechanisms: number;
  accuracy_pct: number;
  scorecard: BenchmarkScorecardItem[];
}

export async function fetchSyntheticManifest(): Promise<SyntheticManifest> {
  const res = await fetch(`${API_URL}/api/synthetic/manifest`, {
    credentials: "include",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to fetch synthetic manifest");
  }
  return res.json();
}

export async function generateSyntheticData(): Promise<SyntheticManifest> {
  const res = await fetch(`${API_URL}/api/synthetic/generate`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to generate synthetic data");
  }
  return res.json();
}

export async function loadSyntheticDataset(outputFile: string): Promise<Dataset> {
  const res = await fetch(`${API_URL}/api/synthetic/load/${encodeURIComponent(outputFile)}`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to load synthetic dataset");
  }
  return res.json();
}

export async function fetchBenchmarkScorecard(datasetId: string): Promise<BenchmarkScorecardResponse> {
  const res = await fetch(`${API_URL}/api/synthetic/benchmark/${encodeURIComponent(datasetId)}`, {
    credentials: "include",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to fetch benchmark scorecard");
  }
  return res.json();
}
