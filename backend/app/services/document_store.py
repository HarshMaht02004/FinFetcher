from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings


class DocumentStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_path = self.settings.storage_path
        self.base_path.mkdir(parents=True, exist_ok=True)

    def report_dir(self, report_id: str) -> Path:
        path = self.base_path / report_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def pdf_path(self, report_id: str, filename: str) -> Path:
        return self.report_dir(report_id) / filename

    def pdf_files(self, report_id: str) -> list[Path]:
        return sorted(self.report_dir(report_id).glob("*.pdf"))

    def metadata_path(self, report_id: str) -> Path:
        return self.report_dir(report_id) / "metadata.json"

    def extraction_path(self, report_id: str) -> Path:
        return self.report_dir(report_id) / "extracted.json"

    def excel_path(self, report_id: str) -> Path:
        return self.report_dir(report_id) / "financial_statements.xlsx"

    def full_text_path(self, report_id: str) -> Path:
        return self.report_dir(report_id) / "full_text.txt"

    def vector_dir(self, report_id: str) -> Path:
        path = self.report_dir(report_id) / "vector_store"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_json(self, path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def load_json(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))
