from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


StatementType = Literal["balance_sheet", "profit_and_loss", "cash_flow"]


class StatementRow(BaseModel):
    item: str
    values: dict[str, float | None]
    raw_values: dict[str, str] = Field(default_factory=dict)


class StatementCheck(BaseModel):
    item: str
    year: str
    reported_total: float | None
    calculated_total: float | None
    difference: float | None
    status: Literal["matched", "warning", "missing"]


class StatementData(BaseModel):
    statement_type: StatementType
    title: str
    years: list[str]
    rows: list[StatementRow]
    source_pages: list[int] = Field(default_factory=list)
    confidence: float = 0.0
    totals_check: list[StatementCheck] = Field(default_factory=list)
    row_count: int = 0


class InsightBlock(BaseModel):
    title: str
    content: str


class ReportMetadata(BaseModel):
    report_id: str
    filename: str
    filenames: list[str] = Field(default_factory=list)
    company_name: str | None = None
    years: list[str] = Field(default_factory=list)
    processed_at: str
    vector_store_path: str
    excel_path: str
    source_reports: int = 1


class ExtractionResponse(BaseModel):
    report_id: str
    metadata: ReportMetadata
    statements: dict[StatementType, StatementData]
    insights: list[InsightBlock]


class QueryRequest(BaseModel):
    report_id: str
    question: str


class QueryResponse(BaseModel):
    report_id: str
    question: str
    answer: str
    sources: list[dict[str, Any]]


class UploadResponse(BaseModel):
    report_id: str
    filename: str
    filenames: list[str] = Field(default_factory=list)
    years: list[str]
    company_name: str | None = None


class RawTableCandidate(BaseModel):
    statement_type: StatementType
    title: str
    page_number: int
    dataframe_rows: list[list[str]]
    score: float
