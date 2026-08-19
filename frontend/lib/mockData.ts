import type { Dataset, DatasetResults, DiagnosisResult, ImputationResult, ExplanationResult, MissingnessMatrix } from "./api";

/* ------------------------------------------------------------------ */
/*  Primary Dataset — customer churn (full results)                    */
/* ------------------------------------------------------------------ */
export const mockDataset: Dataset = {
  id: "mock-1",
  filename: "customer_churn_data.csv",
  row_count: 5000,
  column_names: [
    "CustomerID", "Age", "Gender", "Tenure", "MonthlyCharge",
    "TotalCharge", "ContractType", "Churn",
  ],
  numeric_columns: ["Age", "Tenure", "MonthlyCharge", "TotalCharge"],
  categorical_columns: ["CustomerID", "Gender", "ContractType", "Churn"],
  uploaded_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), // 2 hours ago
};

export const mockDiagnosisResults: DiagnosisResult[] = [
  {
    id: "diag-1",
    target_column: "Age",
    diagnosed_mechanism: "MAR",
    diagnosis_detail:
      "Missingness in Age is significantly correlated with Tenure (p = 0.01). Customers with shorter tenure are more likely to have missing Age values, suggesting data was collected differently for newer customers.",
    littles_p_value: 0.03,
    littles_suggests_mcar: false,
    categorical_assoc_p_values: { Gender: 0.42, ContractType: 0.38 },
    numeric_assoc_p_values: { Tenure: 0.01, MonthlyCharge: 0.22 },
    significant_drivers: ["Tenure"],
    n_missing: 150,
  },
  {
    id: "diag-2",
    target_column: "TotalCharge",
    diagnosed_mechanism: "MCAR",
    diagnosis_detail:
      "No significant associations found between missingness in TotalCharge and any other variable. Little's MCAR test supports completely random missingness (p = 0.45).",
    littles_p_value: 0.45,
    littles_suggests_mcar: true,
    categorical_assoc_p_values: { Gender: 0.67, ContractType: 0.81 },
    numeric_assoc_p_values: { Age: 0.55, Tenure: 0.39, MonthlyCharge: 0.72 },
    significant_drivers: [],
    n_missing: 50,
  },
  {
    id: "diag-3",
    target_column: "MonthlyCharge",
    diagnosed_mechanism: "Ambiguous (MCAR/MNAR)",
    diagnosis_detail:
      "The missingness pattern is ambiguous. While Little's test rejects MCAR (p = 0.04), the association analysis found no strong predictors. This could indicate the missingness is related to MonthlyCharge values themselves (MNAR), but we cannot confirm without domain knowledge.",
    littles_p_value: 0.04,
    littles_suggests_mcar: false,
    categorical_assoc_p_values: { Gender: 0.18, ContractType: 0.09 },
    numeric_assoc_p_values: { Age: 0.31, Tenure: 0.14 },
    significant_drivers: [],
    n_missing: 87,
  },
  {
    id: "diag-4",
    target_column: "Gender",
    diagnosed_mechanism: "MAR",
    diagnosis_detail:
      "Gender missingness is driven by ContractType (p = 0.002). Customers on month-to-month contracts are significantly more likely to have missing Gender values, suggesting certain registration forms skipped this field.",
    littles_p_value: 0.01,
    littles_suggests_mcar: false,
    categorical_assoc_p_values: { ContractType: 0.002, Churn: 0.15 },
    numeric_assoc_p_values: { Age: 0.08, Tenure: 0.12 },
    significant_drivers: ["ContractType"],
    n_missing: 210,
  },
];

export const mockImputationResults: ImputationResult[] = [
  {
    id: "imp-1",
    target_column: "Age",
    routed_mechanism: "MAR",
    method_used: "Iterative Imputer (MICE)",
    low_confidence: false,
    rationale:
      "Used Iterative Imputer (MICE) because missingness was diagnosed as MAR driven by Tenure. The model iteratively predicts Age using all other features, leveraging the observed correlation with Tenure for accurate imputation.",
    n_imputed: 150,
    imputed_file_path: "/data/imputed/mock-1-age.csv",
  },
  {
    id: "imp-2",
    target_column: "TotalCharge",
    routed_mechanism: "MCAR",
    method_used: "MICE",
    low_confidence: false,
    rationale:
      "Chained equations with posterior draws. Mean imputation is unbiased only for the mean and biases regression weights and correlations even under MCAR (van Buuren 2018, Table 1.1), so the conditional model is used here too.",
    n_imputed: 50,
    imputed_file_path: "/data/imputed/mock-1-totalcharge.csv",
  },
  {
    id: "imp-3",
    target_column: "MonthlyCharge",
    routed_mechanism: "Ambiguous (MCAR/MNAR)",
    method_used: "Predictive Mean Matching",
    low_confidence: true,
    rationale:
      "Due to an ambiguous diagnosis, Predictive Mean Matching was used as a conservative method. This approach preserves the distribution shape but may underestimate extreme values if the data is truly MNAR. Review recommended.",
    n_imputed: 87,
    imputed_file_path: "/data/imputed/mock-1-monthlycharge.csv",
  },
  {
    id: "imp-4",
    target_column: "Gender",
    routed_mechanism: "MAR",
    method_used: "Mode Imputation (Conditional)",
    low_confidence: false,
    rationale:
      "Conditional mode imputation based on ContractType. For each contract type, the most frequent gender value was used to fill missing entries, preserving the observed distribution within each group.",
    n_imputed: 210,
    imputed_file_path: "/data/imputed/mock-1-gender.csv",
  },
];

export const mockExplanationResults: ExplanationResult[] = [
  {
    id: "exp-1",
    generated_by: "gemini",
    overall_summary:
      "This customer churn dataset contained missing values across four columns: Age (150 missing), Gender (210 missing), MonthlyCharge (87 missing), and TotalCharge (50 missing). Our analysis identified two columns with MAR (Missing At Random) patterns driven by specific variables, one MCAR (Missing Completely At Random) column, and one ambiguous case requiring human review. Tailored imputation strategies were applied to each column to preserve data integrity while minimising bias.",
    columns_json: [
      {
        target_column: "Age",
        plain_language_summary:
          "Age information was missing for about 150 customers. The missingness is strongly linked to customer tenure — newer customers were more likely to have missing ages.",
        what_this_means_for_the_data:
          "If we simply deleted these rows, we'd lose a disproportionate number of newer customers, which would skew churn analysis toward long-tenure customers and potentially underestimate early churn risk.",
        imputation_explanation:
          "We used a machine-learning model (Iterative Imputer / MICE) that predicts each missing age based on the customer's other attributes — especially tenure, which showed the strongest correlation.",
        confidence_note:
          "High confidence — the Tenure–Age correlation (p = 0.01) gives the model strong signal for accurate predictions.",
        recommended_action:
          "Proceed with analysis using the imputed dataset. The imputed ages are well-supported by the data.",
      },
      {
        target_column: "TotalCharge",
        plain_language_summary:
          "A small number of TotalCharge values (50 out of 5,000) were missing, with no observable pattern.",
        what_this_means_for_the_data:
          "Because the missingness appears completely random, it's unlikely to introduce systematic bias. The impact on analysis is minimal.",
        imputation_explanation:
          "We filled in the missing values using the dataset's mean TotalCharge. This is a standard, unbiased approach for MCAR data.",
        confidence_note:
          "Standard procedure for completely random missing data. Be aware of slightly reduced variance in this column.",
        recommended_action:
          "Safe to use for general reporting and modelling.",
      },
      {
        target_column: "MonthlyCharge",
        plain_language_summary:
          "87 MonthlyCharge values were missing, and the pattern was ambiguous — we couldn't rule out that the values are missing because of the charges themselves.",
        what_this_means_for_the_data:
          "If higher or lower monthly charges are more likely to be missing, this could bias any pricing or revenue analysis. Caution is warranted.",
        imputation_explanation:
          "We used Predictive Mean Matching, a conservative method that fills each gap with a real observed value from a similar customer. This avoids generating unrealistic values.",
        confidence_note:
          "Low confidence — the ambiguous diagnosis means the imputed values may not fully capture the true distribution. If you know why these values are missing, providing that context could improve results.",
        recommended_action:
          "Review this column before critical analysis. Consider running a sensitivity analysis with and without these imputed values.",
      },
      {
        target_column: "Gender",
        plain_language_summary:
          "Gender was missing for 210 customers, primarily those on month-to-month contracts — suggesting a form or system that didn't capture this field for certain plans.",
        what_this_means_for_the_data:
          "Without imputation, any gender-based segmentation would exclude a large chunk of month-to-month customers, biasing results toward customers on longer contracts.",
        imputation_explanation:
          "We used conditional mode imputation: for each contract type, we filled missing genders with the most common gender in that group, preserving the observed distribution.",
        confidence_note:
          "High confidence — the mechanism is clear (MAR driven by ContractType), and the method preserves group-level proportions.",
        recommended_action:
          "Proceed with analysis. The categorical imputation is well-suited for this pattern.",
      },
    ],
  },
];

export const mockDatasetResults: DatasetResults = {
  dataset: mockDataset,
  diagnosis_results: mockDiagnosisResults,
  imputation_results: mockImputationResults,
  explanation_results: mockExplanationResults,
};

/* ------------------------------------------------------------------ */
/*  Additional sidebar datasets (no results — just to populate list)   */
/* ------------------------------------------------------------------ */
export const mockDatasets: Dataset[] = [
  mockDataset,
  {
    id: "mock-2",
    filename: "patient_vitals_q3.csv",
    row_count: 12340,
    column_names: ["PatientID", "HeartRate", "BP_Systolic", "BP_Diastolic", "SpO2", "Temp", "Timestamp"],
    numeric_columns: ["HeartRate", "BP_Systolic", "BP_Diastolic", "SpO2", "Temp"],
    categorical_columns: ["PatientID", "Timestamp"],
    uploaded_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(), // 1 day ago
  },
  {
    id: "mock-3",
    filename: "survey_responses_2024.csv",
    row_count: 892,
    column_names: ["ResponseID", "Satisfaction", "NPS", "Age", "Region", "Comments"],
    numeric_columns: ["Satisfaction", "NPS", "Age"],
    categorical_columns: ["ResponseID", "Region", "Comments"],
    uploaded_at: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(), // 3 days ago
  },
];

export const mockMissingnessMatrix: MissingnessMatrix = {
  columns: ["Age", "TotalCharge", "MonthlyCharge", "Gender"],
  matrix: [
    [1.00, 0.05, 0.12, 0.35],
    [0.05, 1.00, 0.02, 0.08],
    [0.12, 0.02, 1.00, 0.18],
    [0.35, 0.08, 0.18, 1.00],
  ],
  row_count: 5000,
};
