# ImputeIQ — Missing Data Profiling, Mechanism Diagnosis & Imputation Platform

[![Next.js 16](https://img.shields.io/badge/Next.js-16--App--Router-black.svg)](https://nextjs.org/)
[![React 19](https://img.shields.io/badge/React-19-blue.svg)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green.svg)](https://fastapi.tiangolo.com/)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**ImputeIQ** is an end-to-end, enterprise data quality platform designed for missing data profiling, statistical mechanism diagnosis (MCAR, MAR, MNAR), intelligent imputation routing, sensitivity analysis, synthetic benchmarking, and LLM-assisted explanation generation.

---

## 🌟 Key Features

- 📊 **Missingness Profiling & Semantic Auto-Discovery**: Automatically infers column semantic types (numerical, categorical, datetime, identifiers) and calculates missingness rates, pattern correlations, and heatmap distributions.
- 🔬 **Statistical Mechanism Diagnosis Engine**: Runs Little's MCAR test, correlation tests, and distribution shift metrics to classify missing data mechanisms into:
  - **MCAR** (Missing Completely at Random)
  - **MAR** (Missing at Random)
  - **MNAR** (Missing Not at Random)
- 🔀 **Intelligent Method Router & Imputation Engine**: Dynamically routes columns to optimal imputation algorithms based on semantic type and mechanism diagnosis:
  - Mean / Median / Mode Imputation
  - K-Nearest Neighbors (KNN) Imputation
  - Multivariate Imputation by Chained Equations (MICE)
  - MissForest (Random Forest-based non-parametric imputation)
- 📈 **Sensitivity Analysis Engine**: Evaluates model stability and parameter variance across varying missingness proportions and distributional assumptions.
- 🧪 **Synthetic Missingness Benchmark Engine**: Injects synthetic MCAR/MAR/MNAR patterns into complete benchmark datasets to evaluate imputation error metrics (RMSE, MAE, Kolmogorov-Smirnov distance).
- 🤖 **LLM-Assisted Explanations (Gemini Integration)**: Leverages LLM reasoning to translate complex statistical diagnostic outputs into actionable, human-readable insights and compliance recommendations.
- ⚡ **Real-Time Progress & WebSockets**: Live progress updates for long-running imputation jobs via Socket.IO / WebSockets.
- 📄 **PDF Report Generation**: Automated generation of detailed PDF summary reports featuring diagnostic findings, benchmark scorecards, and audit logs.

---

## 🏗️ Architecture Overview

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Next.js 16 Dashboard                            │
│  (React 19, Redux Toolkit, Tailwind CSS v4, Framer Motion, Socket.IO)  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / WebSockets
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                          FastAPI Backend Service                       │
│ ┌──────────────────────┬──────────────────────┬──────────────────────┐ │
│ │  Profiling Engine    │  Mechanism Diagnosis │  Method Router       │ │
│ ├──────────────────────┼──────────────────────┼──────────────────────┤ │
│ │  Imputation Engine   │  Sensitivity Engine  │  Synthetic Benchmark │ │
│ └──────────────────────┴──────────────────────┴──────────────────────┘ │
└──────────────────┬─────────────────────────────────┬───────────────────┘
                   │                                 │
                   ▼                                 ▼
┌───────────────────────────────────┐    ┌───────────────────────────────┐
│     Gemini API LLM Explainer      │    │  SQLite / DB Persistence      │
└───────────────────────────────────┘    └───────────────────────────────┘
```

---

## 📂 Repository Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── api/                   # FastAPI route handlers (diagnosis, imputation, LLM, synthetic)
│   │   ├── core/                  # Core algorithms & engine modules
│   │   │   ├── column_semantics.py      # Column type detection & semantic classification
│   │   │   ├── diagnose_mechanism.py    # MCAR/MAR/MNAR statistical tests
│   │   │   ├── imputation_engine.py     # KNN, MICE, Mean/Median, MissForest algorithms
│   │   │   ├── method_router.py         # Smart algorithm routing matrix
│   │   │   ├── sensitivity_engine.py    # Sensitivity analysis & stability metrics
│   │   │   ├── synthetic_missingness.py # Synthetic benchmark error evaluation
│   │   │   ├── llm_explainer.py         # Gemini LLM insight generator
│   │   │   └── export_report.py         # PDF report generator (ReportLab)
│   │   ├── models/                # SQLAlchemy database models
│   │   ├── schemas/               # Pydantic request/response schemas
│   │   ├── db.py                  # Database session management
│   │   └── main.py                # FastAPI entry point
│   ├── Dockerfile                 # Backend container image build
│   └── requirements.txt           # Python backend dependencies
├── frontend/
│   ├── app/                       # Next.js 16 App Router pages
│   ├── components/                # React UI components (Dashboard, Tabs, Upload Dropzone)
│   │   ├── tabs/                  # Overview, Diagnosis, Imputation, Sensitivity tabs
│   │   └── validation/            # Validation gates & benchmark scorecards
│   ├── lib/                       # API clients & Socket.IO hooks
│   ├── store/                     # Redux Toolkit global state store
│   ├── Dockerfile                 # Frontend container image build
│   └── package.json               # Node.js dependencies
├── docs/                          # Project documentation & dataset specs
├── notebook/                      # Jupyter notebooks for exploratory data analysis (EDA)
├── docker-compose.yml             # Full-stack Docker orchestration
└── README.md                      # Project documentation
```

---

## ⚡ Quick Start (Docker)

The fastest way to launch the entire stack (Frontend + Backend):

### 1. Clone & Configure Environment
```bash
git clone https://github.com/Amaljiththedev/ImputeIQ-.git
cd ImputeIQ-

# Copy environment template
cp .env.example .env
```

Edit `.env` to include your Gemini API key:
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### 2. Build & Launch Containers
```bash
docker compose up --build -d
```

### 3. Access Services
- 🌐 **Frontend Dashboard**: `http://localhost:3000`
- ⚡ **Backend API**: `http://localhost:8000`
- 📖 **Interactive API Docs (Swagger)**: `http://localhost:8000/docs`

---

## 🔧 Local Manual Setup

### 1. Backend Setup (FastAPI)
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend Setup (Next.js)
```bash
cd frontend
npm install
npm run dev
```

The frontend will run at `http://localhost:3000`.

---

## 🧪 Benchmark & Smoke Tests

Run smoke tests for the backend diagnosis and imputation pipeline:

```bash
cd backend
python scripts/smoke_test.py
python scripts/test_llm_explainer.py
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
