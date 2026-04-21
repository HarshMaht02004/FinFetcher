from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.models.schemas import ExtractionResponse, InsightBlock, QueryResponse, ReportMetadata, UploadResponse
from app.services.document_store import DocumentStore
from app.services.excel_service import ExcelService
from app.services.pdf_extractor import PDFExtractor
from app.services.rag_service import RagService
from app.services.statement_service import StatementService


class ReportService:
    def __init__(self) -> None:
        self.store = DocumentStore()
        self.extractor = PDFExtractor()
        self.excel = ExcelService()
        self.rag = RagService()
        self.statement_service = StatementService()

    async def ingest_report(self, files: list[UploadFile]) -> UploadResponse:
        report_id = uuid4().hex
        filenames: list[str] = []
        saved_files: list[tuple[str, Path]] = []

        for index, file in enumerate(files, start=1):
            filename = Path(file.filename or f"{report_id}_{index}.pdf").name
            filenames.append(filename)
            pdf_path = self.store.pdf_path(report_id, filename)
            pdf_path.write_bytes(await file.read())
            saved_files.append((filename, pdf_path))

        extraction_jobs = [
            asyncio.to_thread(self.extractor.extract, pdf_path)
            for _, pdf_path in saved_files
        ]
        extraction_results = await asyncio.gather(*extraction_jobs)

        full_text_parts: list[str] = []
        per_report_statements = []
        company_name: str | None = None
        detected_years: set[str] = set()

        for statements, years, extracted_company_name, full_text in extraction_results:
            per_report_statements.append(statements)
            full_text_parts.append(full_text)
            detected_years.update(years)
            if extracted_company_name and not company_name:
                company_name = extracted_company_name

        statements = self.statement_service.merge_reports(per_report_statements)
        years = sorted(detected_years)
        excel_path = self.store.excel_path(report_id)
        self.excel.build_workbook(statements, excel_path)

        combined_text = "\n\n".join(full_text_parts)
        self.store.full_text_path(report_id).write_text(combined_text, encoding="utf-8")
        vector_dir = self.store.vector_dir(report_id)
        self.rag.build_chunks(report_id, combined_text, vector_dir)

        insights_payload = self.rag.generate_insights(statements, combined_text)
        metadata = ReportMetadata(
            report_id=report_id,
            filename=filenames[0],
            filenames=filenames,
            company_name=company_name,
            years=years,
            processed_at=datetime.now(timezone.utc).isoformat(),
            vector_store_path=str(vector_dir),
            excel_path=str(excel_path),
            source_reports=len(filenames),
        )
        extraction = ExtractionResponse(
            report_id=report_id,
            metadata=metadata,
            statements=statements,
            insights=[InsightBlock(**item) for item in insights_payload],
        )

        self.store.save_json(self.store.metadata_path(report_id), metadata.model_dump())
        self.store.save_json(self.store.extraction_path(report_id), extraction.model_dump())

        return UploadResponse(
            report_id=report_id,
            filename=filenames[0],
            filenames=filenames,
            years=years,
            company_name=company_name,
        )

    def get_extraction(self, report_id: str) -> ExtractionResponse:
        self._ensure_fresh_report(report_id)
        payload = self.store.load_json(self.store.extraction_path(report_id))
        return ExtractionResponse.model_validate(payload)

    def query_report(self, report_id: str, question: str) -> QueryResponse:
        self._ensure_fresh_report(report_id)
        metadata = ReportMetadata.model_validate(self.store.load_json(self.store.metadata_path(report_id)))
        full_text_path = self.store.full_text_path(report_id)
        vector_dir = Path(metadata.vector_store_path)
        if not (vector_dir / "chunks.json").exists() and full_text_path.exists():
            self.rag.build_chunks(report_id, full_text_path.read_text(encoding="utf-8"), vector_dir)
        if self.rag.llm_enabled() and not self.rag.vector_store_exists(vector_dir) and full_text_path.exists():
            self.rag.build_index(report_id, full_text_path.read_text(encoding="utf-8"), vector_dir)
        answer, sources = self.rag.answer_query(report_id, vector_dir, question)
        return QueryResponse(report_id=report_id, question=question, answer=answer, sources=sources)

    def excel_file(self, report_id: str) -> Path:
        self._ensure_fresh_report(report_id)
        extraction = ExtractionResponse.model_validate(self.store.load_json(self.store.extraction_path(report_id)))
        excel_path = self.store.excel_path(report_id)
        self.excel.build_workbook(extraction.statements, excel_path)
        return excel_path

    def _ensure_fresh_report(self, report_id: str) -> None:
        extraction_path = self.store.extraction_path(report_id)
        metadata_path = self.store.metadata_path(report_id)
        if not extraction_path.exists() or not metadata_path.exists():
            raise FileNotFoundError(report_id)
        extraction = ExtractionResponse.model_validate(self.store.load_json(extraction_path))
        if self._extraction_needs_rebuild(extraction):
            self._rebuild_saved_report(report_id)

    def _extraction_needs_rebuild(self, extraction: ExtractionResponse) -> bool:
        for statement in extraction.statements.values():
            if statement.rows and not statement.years:
                return True
            if statement.rows and all(
                all(value is None for value in row.values.values())
                for row in statement.rows
            ):
                return True
        return False

    def _rebuild_saved_report(self, report_id: str) -> None:
        pdf_files = self.store.pdf_files(report_id)
        if not pdf_files:
            raise FileNotFoundError(report_id)

        filenames: list[str] = []
        full_text_parts: list[str] = []
        per_report_statements = []
        company_name: str | None = None
        detected_years: set[str] = set()

        for pdf_path in pdf_files:
            filenames.append(pdf_path.name)
            statements, years, extracted_company_name, full_text = self.extractor.extract(pdf_path)
            per_report_statements.append(statements)
            full_text_parts.append(full_text)
            detected_years.update(years)
            if extracted_company_name and not company_name:
                company_name = extracted_company_name

        statements = self.statement_service.merge_reports(per_report_statements)
        years = sorted(detected_years)
        excel_path = self.store.excel_path(report_id)
        self.excel.build_workbook(statements, excel_path)

        combined_text = "\n\n".join(full_text_parts)
        self.store.full_text_path(report_id).write_text(combined_text, encoding="utf-8")
        vector_dir = self.store.vector_dir(report_id)
        self.rag.build_chunks(report_id, combined_text, vector_dir)
        insights_payload = self.rag.generate_insights(statements, combined_text)

        existing_metadata = ReportMetadata.model_validate(self.store.load_json(self.store.metadata_path(report_id)))
        metadata = ReportMetadata(
            report_id=report_id,
            filename=filenames[0],
            filenames=filenames,
            company_name=company_name,
            years=years,
            processed_at=datetime.now(timezone.utc).isoformat(),
            vector_store_path=str(vector_dir),
            excel_path=str(excel_path),
            source_reports=len(filenames),
        )
        if existing_metadata.company_name and not company_name:
            metadata.company_name = existing_metadata.company_name

        extraction = ExtractionResponse(
            report_id=report_id,
            metadata=metadata,
            statements=statements,
            insights=[InsightBlock(**item) for item in insights_payload],
        )
        self.store.save_json(self.store.metadata_path(report_id), metadata.model_dump())
        self.store.save_json(self.store.extraction_path(report_id), extraction.model_dump())
