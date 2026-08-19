# ImputeIQ — handoff

Written to transfer context to a new session. Read this first.

Student: Amaljith. Supervisor: Dr Olga Anosova, University of Liverpool.
MSc dissertation. Deadline is close; a 10-minute milestone demonstration video
is due.

---

## 1. What the project is

A full-stack tool for handling missing data in clinical datasets, aimed at CPRD
Aurum. Its distinguishing claim is that it finds missing values that **do not
look missing** — a blood pressure recorded as `0`, a cholesterol of `-999`, a
region of `"Unknown"` — then diagnoses *why* data is missing and imputes with a
method matched to that reason and to what the column actually is.

Backend FastAPI + Postgres in Docker. Frontend Next.js run directly with npm.
Language model: **Groq**, `openai/gpt-oss-120b`.

---

## 2. Running and verifying it

```bash
# backend + database
docker compose up -d --build backend

# frontend (separate, not containerised)
cd frontend && npm run dev

# tests (115 passing)
docker exec -i dissertation-backend-1 sh -c "cd /app && python -m pytest"

# typecheck
cd frontend && npx tsc --noEmit
```

Ports: backend 8000, frontend 3000, Postgres 5433.

**Operational gotchas that have cost time in this project:**

- `docker compose restart` does **not** re-read `.env`. Use
  `docker compose up -d --force-recreate backend`.
- A plain recreate does **not** pick up `requirements.txt` changes. Use
  `--build`.
- Recreating the container wipes anything installed with `pip install` at
  runtime, including pytest. Re-install or rebuild.
- Docker Desktop has stopped on this machine more than once. Check both
  services are actually up before demoing.
- Scratch scripts copied to `/tmp` inside the container do not survive a
  rebuild.

---

## 3. Where things live

```
backend/app/core/
  validation_service.py   placeholder detection, data dictionary, assumptions
  diagnose_mechanism.py   Little's test, chi-square, Welch, Holm; MechanismClass
  column_semantics.py     identifier / categorical / continuous (CPRD-aware)
  method_router.py        routing precedence and the cited rationale
  imputation_engine.py    9 imputers, PMM, strata detection, Rubin pooling
  pipeline.py             orchestration; both impute paths live here
  sensitivity_engine.py   variance retention, standardised mean shift, MNAR bound
  llm_client.py           the ONLY place the provider is called
  llm_explainer.py        explanation prose + deterministic fallback
backend/app/api/routes.py            main API
backend/app/api/routes_synthetic.py  benchmark scorecard
backend/tests/                       115 tests, mostly regression tests
docs/methods-reference.md            the document the supervisor reads
frontend/components/validation/ValidationGate.tsx    the most important screen
frontend/components/imputation/ApprovalScreen.tsx    the real approval flow
frontend/app/globals.css             design tokens and glass materials
```

---

## 4. The pipeline

1. Upload. The original file is never modified; all work happens on a copy.
2. Profile every column; screen for placeholder candidates (`0`, `-999`, `999`,
   `-99`, `-1`, `"unknown"`, `"n/a"`, `"na"`, `"null"`, `"none"`, `"?"`, empty).
3. Judge each candidate semantically. A user-supplied data dictionary wins;
   otherwise the model judges from column name and statistics.
4. **State the assumed meaning of every column and require confirmation** before
   anything is applied. This was a direct supervisor requirement.
5. Convert approved placeholders to NaN on the copy.
6. Diagnose mechanism — **no LLM involved**: Little's test (pyampute),
   chi-square on the missingness indicator, Welch's t-test, Holm-Bonferroni.
7. Classify semantic role.
8. Route. Precedence: identifier → `flag_only`; categorical → `mode`;
   structural zero → `zero`; else MAR/MCAR → `pmm`, MNAR → `median` + low
   confidence.
9. User reviews and can override every column.
10. Impute, with stratification where needed.
11. Report sensitivity and a plain-language explanation.

---

## 5. Defects fixed — do not reintroduce

Each has a regression test. The reasons matter; several look like harmless
simplifications.

| Defect | Why it mattered |
|---|---|
| `_generate_fallback_explanation` was called but never existed | Any model outage crashed the whole job |
| Model pinned to an unavailable version | Every run silently used fallbacks |
| String placeholders replaced case-sensitively | Detection reports `"unknown"`, data holds `"Unknown"`, so nothing converted and the column dropped out of the analysis entirely |
| Sensitivity scored on mean shift only | Median barely moves a mean, so every column scored an identical 85 while variance collapsed |
| `missingPct` held a fraction | Understated missingness 100-fold |
| Frontend synthesised metrics from hardcoded constants | Fabricated numbers rendered indistinguishably from real ones |
| `/datasets/[id]/approve` page | Made **zero** API calls; approving did nothing; showed invented "18.3% error" figures |
| Benchmark scored by substring | `"Ambiguous (MCAR/MNAR)"` matched both MCAR and MNAR, so a non-classification counted as correct → 100% accuracy |
| `littles_suggests_mcar` | Treated failure-to-reject as evidence for MCAR |
| `"Likely MNAR (by elimination)"` | Not supportable; now `Undetermined` |
| `IterativeImputer(sample_posterior=False)` | Deterministic, so not MICE at all |
| MAR routed to median | Biased precisely where the driver was known (van Buuren Table 1.1) |
| `sample_posterior=True` unbounded | Produced **453 negative clinical measurements**; replaced by PMM |
| Structural-zero heuristic too loose | Zero-filled reference ranges, asserting a normal range of 0 |
| `semantic_role` never passed to that heuristic | Its guard was dead code |
| Long-format `value` column imputed as one variable | Pooled BP, BMI, cholesterol, HbA1c; inflated all of them |
| 100%-missing column | Crashed the approval job (`Columns must be same length as key`) |
| Model returns action synonyms | `"replace_with_null"` read as "keep"; placeholders survived. Happened 3× |
| Cache insert race | `IntegrityError` surfaced in the browser as a misleading CORS error |
| PMM missing from UI method lists | Recommended method wasn't selectable in the dropdown |

**Do not "simplify" the action normaliser, the fully-absent-column guard, or the
stratification check.** Each exists because of an observed failure on real
CPRD-shaped data.

---

## 6. Outstanding

**Blocked on the supervisor**

- She has **not yet approved** the MAR→PMM routing change. It is already
  implemented. She must be told, not left to discover it.
- She asked Amaljith to match the methods table against the routing rules
  **himself, without AI**. Do not write that analysis for him. Help him
  understand it and review his draft.

**Blocked on Amaljith**

- Real citations in his own reading. She stated explicitly that an LLM is not a
  valid source.
- ~38 uncommitted files; he handles git himself.

**Open engineering**

- Rubin pooling is implemented and tested but **nothing calls it**. The
  downloaded CSV is a single imputation, so standard errors from it are too
  small.
- Rows are treated as independent. CPRD has many rows per patient, and a
  patient's own other measurements are likely the best predictor. Arguably the
  biggest remaining statistical limitation.
- `GEMINI_API_KEY` is still in `.env`, unused, and was once committed in
  `.env.example`. Should be rotated.
- The interface has **never been visually verified** by the assistant. The
  Browser pane is not displayed in these sessions, so screenshots fail and
  `requestAnimationFrame` is frozen, which deadlocks tab switching in
  `AnimatePresence`. Ten components were restyled and checked only by computed
  CSS. Amaljith must look at it himself.

---

## 7. Supervisor context

Dr Anosova replies within two working days and **prefers one consolidated email**
— Outlook collapses threads and she misses questions.

Her positions so far:

- Implementation decisions must come from **published properties of the methods
  with references**, not from experiments on one dataset, and **not from an LLM**.
  She asked directly whether the original routing rules came from an LLM.
- Wikipedia is acceptable as a citable source.
- Use **pre-set classes** rather than string matching for scoring. Implemented as
  `MechanismClass` in `diagnose_mechanism.py`.
- Limitations belong in the conclusion slide; markers want critical evaluation.
- Video: four parts — problem slides, tool demo, code demo, conclusion. 10
  minutes. Broad overview, then concentrate on the tricky parts.

**Two questions of hers still unanswered:**

1. *Where does the CPRD data come from?* The answer must be unambiguous: it is
   **synthetic data generated to CPRD Aurum specification v2.9**. No real patient
   records, no approval required. Only the structure follows the spec.
2. *Is there sensitivity/robustness analysis, or only ground-truth comparison?*
   Honest answer: the tool computes per-column sensitivity (variance retention,
   standardised mean shift, ±1 SD delta-adjusted MNAR bound), but the
   **evaluation** has leaned on ground-truth comparison. The sensitivity output
   exists; it is not yet the basis of the evaluation.

She also challenged the claim that the interesting parts are "hard to see on
screen". She was right — placeholder detection, driver identification and routing
are all already visible in the UI. That claim should be conceded.

---

## 8. Test data

Generators live in the session scratchpad and outputs in the project root:

- `cprd_aurum_observation_synthetic.csv` (2,000 rows) + dictionary — best demo
  material: placeholder detection, a named MAR driver, identifiers left
  unimputed, long-format stratification by `medcodeid`.
- `cprd_aurum_drugissue_synthetic.csv` (2,500 rows) + dictionary — stratification
  by `prodcodeid` across a 58× quantity range, and the 100%-absent `dosageid`.
- `imputeiq_demo_dataset.csv` (1,200 rows) — generic clinical, planted ground
  truth.

All synthetic. Regenerate with the scripts if lost.

---

## 9. Known limitations (for the dissertation and the video)

- MNAR cannot be identified from observed data. This is a property of the data,
  not the tool.
- Little's test is computed **once for the whole dataset** and shared across
  columns, so a per-column "consistent with MCAR" is partly borrowed.
- Rows assumed independent; repeated measures per patient not exploited.
- Output is single imputation; standard errors from it are too small.
- PMM drifts in small strata (few donors).
- Placeholder judgement depends on a language model — not perfectly repeatable,
  and it can overrule the sentinel rules.
- Thresholds are judgement calls: structural zero >30% missing, max ≤20,
  <10 distinct; stratification eta² ≥ 0.5; stability bands 0.95/0.90;
  MNAR delta ±1 SD.
- One table at a time; no joins.
- Dates never used as predictors or imputed.
- Categorical gaps only ever get the mode.
- KNN does not standardise features first.

---

## 10. How to work on this

Verify empirically rather than asserting. This project has repeatedly looked
correct and been wrong underneath — fabricated UI numbers, a scoring bug
reporting 100%, an approval page that silently discarded input. When something
passes, say what was actually checked. When it fails, say so with the output.
