# EDA Findings — patient_records_clean.csv

Generated from patient_records_descriptive_eda.ipynb
Dataset: 382 rows, 10 columns, 0 missing values

## Masking recommendations

- Numeric target: glucose (CV 26.1%)
- Categorical target: smoking_status (Current minority 21.7%)
- MAR driver: age -> systolic_bp (r=0.125)
