# Financial Report RAG Analyzer

Production-oriented web application for extracting structured financial statements from annual report PDFs, exporting them to Excel, and answering grounded natural-language questions with a Retrieval-Augmented Generation (RAG) pipeline.

## What it does

- Upload a company annual report PDF
- Detect consolidated Balance Sheet, Profit & Loss, and Cash Flow statements
- Extract two-year structured financial tables
- Export the extracted statements to Excel
- Build a vector index over the report for grounded Q&A
- Generate report insights using an LLM with retrieval-backed context

## Architecture

- Backend: FastAPI
- Extraction: `pdfplumber` with optional `PyMuPDF` and `camelot`
- Structuring: `pandas`
- Excel export: `openpyxl`
- RAG: LangChain + configurable OpenAI or local embeddings/LLM
- Vector store: FAISS or Chroma
- Frontend: React + Vite

## Project layout

- `backend/app/main.py`: FastAPI entrypoint
- `backend/app/api/routes.py`: API routes
- `backend/app/services/`: extraction, RAG, Excel, orchestration services
- `frontend/src/App.jsx`: main React app

## Backend setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Frontend expects the backend at `http://localhost:8000`.

## Environment

Copy `backend/.env.example` to `backend/.env` and adjust values as needed.

Important variables:

- `OPENAI_API_KEY`: required for OpenAI embeddings/chat
- `LLM_PROVIDER`: `openai` or `local`
- `VECTOR_STORE`: `faiss` or `chroma`
- `LOCAL_LLM_BASE_URL`: local OpenAI-compatible endpoint, if used
- `LOCAL_EMBEDDING_MODEL`: local embedding model name

## API

- `POST /upload`
  - multipart form-data with `file`
  - uploads and processes a PDF
- `GET /extract?report_id=<id>`
  - returns extracted statements and generated insights
- `POST /query`
  - JSON body: `{"report_id": "...", "question": "..."}`
- `GET /download?report_id=<id>`
  - downloads generated Excel workbook

## Notes

- Extraction quality depends heavily on the PDF layout. The service uses multi-step fallbacks and section heuristics tuned for annual reports.
- Consolidated statements are prioritized and standalone-only sections are ignored where they can be distinguished from context.
- If exact data cannot be found in the retrieved context, the LLM prompt instructs the model to return `Not found`.
