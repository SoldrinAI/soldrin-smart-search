# Soldrin Smart Search

Upload a CSV/XLSX and search it by meaning. Hybrid ranking: 65% semantic (all-MiniLM-L6-v2 embeddings) + 35% BM25 keywords.

```
frontend/   Vite + React + TypeScript UI
backend/    FastAPI (Python) API + bundled ONNX embedding model (~23 MB, no PyTorch)
vercel.json Deploys both to one Vercel project (UI at /, API at /api/*)
```

The backend is **stateless** (serverless-friendly): the browser holds the index and sends it with each search.
Limits: 1,000 rows, 100 columns, 4 MB (Vercel request-body cap).

## Run locally
```bash
# terminal 1 – API on :8000
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt uvicorn
uvicorn index:app --port 8000

# terminal 2 – UI on :5173 (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

## Deploy
Push to GitHub, then in Vercel: **Add New → Project → import the repo → Deploy** (no settings to change).
