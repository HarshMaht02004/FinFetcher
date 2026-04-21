from __future__ import annotations

from collections import OrderedDict

from app.models.schemas import StatementCheck, StatementData, StatementRow, StatementType


SECTION_ORDER: tuple[StatementType, ...] = ("balance_sheet", "profit_and_loss", "cash_flow")


class StatementService:
    def merge_reports(self, report_statements: list[dict[StatementType, StatementData]]) -> dict[StatementType, StatementData]:
        merged: dict[StatementType, StatementData] = {}
        for statement_type in SECTION_ORDER:
            merged[statement_type] = self._merge_statement_type(
                statement_type,
                [report[statement_type] for report in report_statements if statement_type in report],
            )
        return merged

    def _merge_statement_type(
        self,
        statement_type: StatementType,
        statements: list[StatementData],
    ) -> StatementData:
        if not statements:
            return StatementData(
                statement_type=statement_type,
                title=statement_type.replace("_", " ").title(),
                years=[],
                rows=[],
                source_pages=[],
                confidence=0.0,
                totals_check=[],
                row_count=0,
            )

        all_years = sorted({year for statement in statements for year in statement.years})
        item_order: OrderedDict[str, str] = OrderedDict()
        merged_values: dict[str, dict[str, float | None]] = {}
        merged_raw_values: dict[str, dict[str, str]] = {}
        source_pages: list[int] = []

        for statement in statements:
            source_pages.extend(statement.source_pages)
            for row in statement.rows:
                key = self._normalize_item_key(row.item)
                item_order.setdefault(key, row.item)
                merged_values.setdefault(key, {})
                merged_raw_values.setdefault(key, {})
                for year in statement.years:
                    value = row.values.get(year)
                    if value is not None:
                        merged_values[key][year] = value
                        merged_raw_values[key][year] = row.raw_values.get(year, str(value))
                    elif year not in merged_values[key]:
                        merged_values[key][year] = None

        rows: list[StatementRow] = []
        for key, label in item_order.items():
            values = {year: merged_values.get(key, {}).get(year) for year in all_years}
            raw_values = {
                year: merged_raw_values.get(key, {}).get(year, "")
                for year in all_years
            }
            rows.append(StatementRow(item=label, values=values, raw_values=raw_values))

        checks = self._build_total_checks(rows, all_years)
        confidence = self._calculate_confidence(statements, checks)
        return StatementData(
            statement_type=statement_type,
            title=statements[0].title,
            years=all_years,
            rows=rows,
            source_pages=sorted(set(source_pages)),
            confidence=confidence,
            totals_check=checks,
            row_count=len(rows),
        )

    def _build_total_checks(self, rows: list[StatementRow], years: list[str]) -> list[StatementCheck]:
        checks: list[StatementCheck] = []
        running: list[StatementRow] = []
        for row in rows:
            row_name = row.item.lower()
            if self._is_total_row(row.item):
                for year in years:
                    reported = row.values.get(year)
                    calculated = sum((candidate.values.get(year) or 0.0) for candidate in running)
                    if reported is None:
                        checks.append(
                            StatementCheck(
                                item=row.item,
                                year=year,
                                reported_total=None,
                                calculated_total=calculated,
                                difference=None,
                                status="missing",
                            )
                        )
                        continue
                    difference = round((reported or 0.0) - calculated, 2)
                    checks.append(
                        StatementCheck(
                            item=row.item,
                            year=year,
                            reported_total=reported,
                            calculated_total=calculated,
                            difference=difference,
                            status="matched" if abs(difference) <= 1 else "warning",
                        )
                    )
                running = []
                continue

            if self._is_section_header(row_name):
                running = []
                continue

            running.append(row)
        return checks

    def _calculate_confidence(self, statements: list[StatementData], checks: list[StatementCheck]) -> float:
        total_rows = sum(statement.row_count or len(statement.rows) for statement in statements)
        if total_rows == 0:
            return 0.0
        base = max((statement.confidence for statement in statements), default=0.0)
        if not checks:
            return round(max(base, 0.96), 2)
        matched = sum(1 for check in checks if check.status == "matched")
        ratio = matched / len(checks)
        return round(min(0.99, max(base, 0.9 + (ratio * 0.09))), 2)

    def _normalize_item_key(self, item: str) -> str:
        return " ".join(item.lower().replace("&", "and").split())

    def _is_total_row(self, item: str) -> bool:
        lowered = item.lower().strip()
        return lowered.startswith("total") or "net cash flows from" in lowered or "net cash generated" in lowered

    def _is_section_header(self, item: str) -> bool:
        return item in {
            "assets",
            "equity and liabilities",
            "equity",
            "liabilities",
            "income",
            "expenses",
            "non-current assets",
            "current assets",
            "non-current liabilities",
            "current liabilities",
        }
