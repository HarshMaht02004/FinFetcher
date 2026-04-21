from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.models.schemas import ExtractionResponse, QueryRequest, QueryResponse, UploadResponse
from app.services.report_service import ReportService

router = APIRouter()
service = ReportService()


@router.post("/upload", response_model=UploadResponse)
async def upload_report(files: list[UploadFile] = File(...)) -> UploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="At least one PDF file is required.")
    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    return await service.ingest_report(files)


@router.get("/extract", response_model=ExtractionResponse)
def extract_report(report_id: str) -> ExtractionResponse:
    try:
        return service.get_extraction(report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Report not found.") from exc


@router.post("/query", response_model=QueryResponse)
def query_report(payload: QueryRequest) -> QueryResponse:
    try:
        return service.query_report(payload.report_id, payload.question)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Report not found.") from exc


@router.get("/download")
def download_excel(report_id: str) -> FileResponse:
    try:
        excel_path = service.excel_file(report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Report not found.") from exc
    return FileResponse(
        path=excel_path,
        filename=excel_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
