# ImputeIQ

Full-stack pipeline for missing-data profiling, mechanism diagnosis, imputation, sensitivity analysis, and LLM-assisted recommendations.

## Structure

- `frontend/` — Next.js dashboard
- `backend/` — FastAPI API
- `notebook/` — exploratory analysis notebooks

## Quick start

```bash
docker compose up --build
```

Copy `.env.example` → `.env` and set `GEMINI_API_KEY`.
