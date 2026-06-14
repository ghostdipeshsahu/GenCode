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

## Deployment

Two services: backend on Railway, frontend on Vercel. GitHub Actions runs CI
on every push.

### 1. Push to GitHub

```powershell
git remote add origin https://github.com/<you>/gencode.git
git push -u origin main
```

CI (`.github/workflows/ci.yml`) will run on push:
- Backend job: install requirements, compile-check Python, run
  `scripts/validate_questions.py` which schema-checks every enriched
  question and confirms every reference_code passes its tests.
- Frontend job: install deps, run `npm run build`.

### 2. Backend → Railway

1. Create a new Railway project → "Deploy from GitHub repo".
2. In the service settings, set **Root Directory** to `backend`.
3. Add environment variables:
   - `OPENROUTER_API_KEY` — your OpenRouter key
   - `ALLOWED_ORIGINS` — your Vercel domain (e.g. `https://gencode.vercel.app`).
     Comma-separate multiple domains. Use `*` only for testing.
4. Railway auto-detects Python and uses `Procfile`:
   `web: uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Health check `/api/health` is configured in `railway.json` —
   first deploy succeeds when it returns 200.
6. Copy the public URL (e.g. `https://gencode-backend.up.railway.app`).

### 3. Frontend → Vercel

1. Create a new Vercel project → import the same GitHub repo.
2. Set **Root Directory** to `frontend`.
3. Framework preset auto-detects Vite (build = `npm run build`,
   output = `dist`).
4. Add environment variable:
   - `VITE_API_BASE_URL` = the Railway URL from step 2 (no trailing slash).
5. Deploy.

The `vercel.json` rewrites all paths to `/index.html` so client-side routing
works. `src/api.js` reads `VITE_API_BASE_URL` at build time and prepends it
to every `/api/*` call; locally it stays empty and the Vite dev proxy
handles requests.

### CORS

The backend reads `ALLOWED_ORIGINS` (comma-separated). Set it to your Vercel
domain in production. The default `*` is only for local dev.

## Build order

This system is built in eight numbered steps. See the source build doc for full
spec. Steps 1–3 are pure Python and can be tested without the frontend.

## Stack

- Python 3.11+ / FastAPI
- OpenRouter (OpenAI-compatible), model `openai/gpt-oss-120b:free`
- React 18 + Vite (frontend)
- In-memory session state (no database)
- Railway (backend) + Vercel (frontend) + GitHub Actions (CI)
