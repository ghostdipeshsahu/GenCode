# GenCode

Educational platform that teaches students to supervise AI-generated code by
writing precise English prompts. Students never write Python — they describe a
function in English, a deliberately literal AI converts the description to
Python, and the code is graded against tests.

## How it works

1. Student opens a problem (problem description + requirements checklist + sample tests).
2. Student writes a prompt and submits it.
3. Backend runs a **Code Generator** (constrained LLM) that translates the prompt to Python.
4. Backend runs a **Code Executor** (Python `exec()`) against sample + hidden tests.
5. The **Assessor agent** grades the prompt and returns a score and specific feedback.
6. Student refines the prompt and resubmits until all tests pass.

Questions are pre-enriched offline by the **Author agent** (`scripts/author.py`).

## Project layout

```
gencode/
├── backend/
│   ├── main.py                FastAPI app, all endpoints
│   ├── agents/assessor.py     Assessor agent (eval loop, max 2 retries)
│   ├── core/code_generator.py Constrained LLM → Python
│   ├── core/code_executor.py  exec()-based test runner
│   ├── models/schemas.py      Pydantic contracts
│   └── requirements.txt
├── frontend/                  React SPA (Vite)
│   ├── src/App.jsx
│   └── src/components/         ProblemPanel, PromptEditor,
│                                ResultsPanel, AttemptHistory
├── questions/                 Pre-enriched JSON (one file per question)
└── scripts/author.py          Offline Author agent (eval loop, max 3 retries)
```

## Setup

### Backend
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Put OPENROUTER_API_KEY=... in gencode/backend/.env (gitignored)
uvicorn main:app --reload
```

### Frontend
```powershell
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

Vite proxies `/api/*` to the backend on `:8000`, so you do not need to set
any CORS or base-URL env vars during development. Start the backend first.

## Build order

This system is built in eight numbered steps. See the source build doc for full
spec. Steps 1–3 are pure Python and can be tested without the frontend.

## Stack

- Python 3.11+ / FastAPI
- OpenRouter (OpenAI-compatible), model `openai/gpt-oss-120b:free`
- React 18 + Vite (frontend)
- React (frontend, Step 6)
- In-memory session state (no database)
