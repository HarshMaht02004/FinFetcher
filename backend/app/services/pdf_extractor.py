from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from app.models.schemas import RawTableCandidate, StatementData, StatementRow, StatementType

STATEMENT_KEYWORDS: dict[StatementType, list[str]] = {
    "balance_sheet": [
        "balance sheet",
        "statement of financial position",
        "financial position",
        "assets",
        "liabilities",
    ],
    "profit_and_loss": [
        "statement of profit and loss",
        "profit and loss",
        "statement of income",
        "statement of comprehensive income",
        "revenue",
        "profit after tax",
    ],
    "cash_flow": [
        "cash flow statement",
        "statement of cash flows",
        "net cash generated",
        "cash and cash equivalents",
    ],
}

EXACT_STATEMENT_TITLES: dict[StatementType, list[str]] = {
    "balance_sheet": [
        "consolidated balance sheet",
        "consolidated balance sheet (contd.)",
    ],
    "profit_and_loss": [
        "consolidated statement of profit and loss",
        "consolidated statement of profit and loss (contd.)",
    ],
    "cash_flow": [
        "consolidated statement of cash flows",
        "consolidated statement of cash flows (contd.)",
        "consolidated statement of cash flow",
        "consolidated statement of cash flow (contd.)",
    ],
}

STATEMENT_BODY_HINTS: dict[StatementType, list[str]] = {
    "balance_sheet": [
        "assets",
        "equity and liabilities",
        "total assets",
        "total equity and liabilities",
        "notes as at as at",
    ],
    "profit_and_loss": [
        "income",
        "expenses",
        "profit before tax",
        "profit for the year",
        "notes for the year ended for the year ended",
    ],
    "cash_flow": [
        "cash flow from operating activities",
        "net cash",
        "cash and cash equivalents at the end of the year",
        "indirect method",
    ],
}

CONSOLIDATED_HINTS = [
    "consolidated",
    "group",
    "for the year ended",
]

STANDALONE_HINTS = [
    "standalone",
    "separate financial statements",
]

YEAR_REGEX = re.compile(r"\b(20\d{2})\b")
NUMERIC_TOKEN_REGEX = re.compile(r"^\(?[-+]?\d[\d,.\s]*\)?$")
FISCAL_YEAR_PATTERNS = [
    re.compile(r"March\s+31,?\s*(\d{2,4})", re.IGNORECASE),
    re.compile(r"31(?:st)?[-\s]+March[-,\s]+(\d{2,4})", re.IGNORECASE),
    re.compile(r"31[-\s]*March[-\s]*(\d{2,4})", re.IGNORECASE),
    re.compile(r"\bFY\s*(\d{2,4})[-/](\d{2,4})\b", re.IGNORECASE),
    re.compile(r"\bFY\s*(\d{2,4})\b", re.IGNORECASE),
    re.compile(r"\bFY(\d{2,4})\b", re.IGNORECASE),
]


@dataclass
class PageExtraction:
    page_number: int
    text: str
    tables: list[list[list[str]]]
    segments: list[str]


class PDFExtractor:
    def extract(self, pdf_path: Path) -> tuple[dict[StatementType, StatementData], list[str], str | None, str]:
        pages = self._read_pdf(pdf_path)
        full_text = "\n\n".join(page.text for page in pages if page.text)
        page_statements = self._extract_from_statement_sections(pages)
        text_statements = self._extract_from_full_text_sections(full_text)
        structured_statements = {
            statement_type: self._better_statement_candidate(
                statement_type,
                page_statements.get(statement_type),
                text_statements.get(statement_type),
            )
            for statement_type in EXACT_STATEMENT_TITLES
        }
        company_name = self._detect_company_name(pages, structured_statements)
        years = self._detect_years_from_statements(structured_statements)
        if structured_statements and any(statement.rows for statement in structured_statements.values()):
            return structured_statements, years, company_name, full_text
        candidates = self._collect_candidates(pages)
        statements = self._build_statements(candidates, years)
        return statements, years, company_name, full_text

    def _read_pdf(self, pdf_path: Path) -> list[PageExtraction]:
        pages: list[PageExtraction] = []
        with pdfplumber.open(pdf_path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
                pages.append(PageExtraction(page_number=index, text=text, tables=[], segments=[text]))
        return pages

    def _detect_company_name(
        self,
        pages: list[PageExtraction],
        statements: dict[StatementType, StatementData] | None = None,
    ) -> str | None:
        if statements:
            first_balance = statements.get("balance_sheet")
            if first_balance and first_balance.rows:
                for page_no in first_balance.source_pages:
                    page_text = pages[page_no - 1].text
                    for line in page_text.splitlines():
                        cleaned = " ".join(line.split()).strip()
                        if "limited" in cleaned.lower() and 5 < len(cleaned) < 120:
                            return cleaned
        if not pages:
            return None
        first_page = pages[0].text.splitlines()
        for line in first_page[:12]:
            cleaned = " ".join(line.split()).strip()
            if 5 < len(cleaned) < 100 and any(token in cleaned.lower() for token in ("limited", "ltd", "inc", "corp")):
                return cleaned
        return None

    def _detect_years(self, text: str) -> list[str]:
        years = self._extract_fiscal_years(text)
        return years[-2:] if len(years) >= 2 else years

    def _detect_years_from_statements(self, statements: dict[StatementType, StatementData]) -> list[str]:
        discovered: list[str] = []
        for statement in statements.values():
            for year in statement.years:
                if year not in discovered:
                    discovered.append(year)
        filtered = sorted({year for year in discovered if 2020 <= int(year) <= 2030})
        return filtered[-2:] if len(filtered) >= 2 else filtered

    def _extract_from_statement_sections(
        self,
        pages: list[PageExtraction],
    ) -> dict[StatementType, StatementData]:
        statements: dict[StatementType, StatementData] = {}
        for statement_type, titles in EXACT_STATEMENT_TITLES.items():
            matched_pages = self._find_statement_pages(pages, titles, statement_type)
            statement = self._parse_statement_pages(statement_type, matched_pages)
            statements[statement_type] = statement
        return statements

    def _extract_from_full_text_sections(self, full_text: str) -> dict[StatementType, StatementData]:
        lines = [" ".join(line.split()).strip() for line in full_text.splitlines() if line.strip()]
        statements: dict[StatementType, StatementData] = {}
        for statement_type, titles in EXACT_STATEMENT_TITLES.items():
            candidate_indices = [
                index
                for index, line in enumerate(lines)
                if any(title in line.lower() for title in titles)
            ]
            start_index = (
                max(
                    candidate_indices,
                    key=lambda index: self._full_text_statement_score(lines, index, statement_type),
                )
                if candidate_indices
                else None
            )
            if start_index is None:
                statements[statement_type] = StatementData(
                    statement_type=statement_type,
                    title=statement_type.replace("_", " ").title(),
                    years=[],
                    rows=[],
                    source_pages=[],
                    confidence=0.0,
                    row_count=0,
                )
                continue
            block_lines = self._collect_full_text_block(lines, start_index, statement_type)
            statements[statement_type] = self._parse_statement_lines(
                statement_type=statement_type,
                title=lines[start_index],
                lines=block_lines,
                source_pages=[],
                confidence=0.96,
            )
        return statements

    def _full_text_statement_score(
        self,
        lines: list[str],
        start_index: int,
        statement_type: StatementType,
    ) -> int:
        window = " ".join(lines[start_index : min(len(lines), start_index + 40)]).lower()
        score = 0
        if "particulars" in window:
            score += 3
        if "note" in window:
            score += 2
        if "march 31" in window or "for the year ended" in window:
            score += 2
        score += sum(1 for hint in STATEMENT_BODY_HINTS[statement_type] if hint in window)
        if "adjusted revenue" in window or "management discussion" in window:
            score -= 4
        return score

    def _collect_full_text_block(
        self,
        lines: list[str],
        start_index: int,
        statement_type: StatementType,
    ) -> list[str]:
        other_titles = [
            title
            for other_type, titles in EXACT_STATEMENT_TITLES.items()
            if other_type != statement_type
            for title in titles
        ]
        collected: list[str] = []
        for index in range(start_index, min(len(lines), start_index + 220)):
            line = lines[index]
            lowered = line.lower()
            if index > start_index and any(title in lowered for title in other_titles):
                break
            if index > start_index and lowered.startswith("standalone statement of"):
                break
            if index > start_index and lowered.startswith("notes to consolidated financial statements"):
                break
            collected.append(line)
        return collected

    def _better_statement_candidate(
        self,
        statement_type: StatementType,
        primary: StatementData | None,
        fallback: StatementData | None,
    ) -> StatementData:
        if primary is None and fallback is None:
            return StatementData(
                statement_type=statement_type,
                title=statement_type.replace("_", " ").title(),
                years=[],
                rows=[],
                source_pages=[],
                confidence=0.0,
                row_count=0,
            )
        if primary is None:
            return fallback
        if fallback is None:
            return primary

        primary_value_rows = sum(1 for row in primary.rows if any(value is not None for value in row.values.values()))
        fallback_value_rows = sum(1 for row in fallback.rows if any(value is not None for value in row.values.values()))

        if fallback.years and not primary.years:
            return fallback
        if fallback_value_rows > primary_value_rows:
            return fallback
        if fallback_value_rows == primary_value_rows and len(fallback.rows) > len(primary.rows):
            return fallback
        return primary

    def _find_statement_pages(
        self,
        pages: list[PageExtraction],
        titles: list[str],
        statement_type: StatementType,
    ) -> list[PageExtraction]:
        scored: list[tuple[int, PageExtraction]] = []
        for page in pages:
            first_lines = [
                " ".join(line.split()).strip().lower()
                for line in page.text.splitlines()[:20]
                if line.strip()
            ]
            header_lines = first_lines[:8]
            header_blob = " ".join(header_lines)
            if any(any(title in line for line in header_lines) for title in titles):
                score = self._statement_segment_score(statement_type, page.text, header_blob)
                scored.append((score, page))

        if not scored:
            return []

        best_score = max(score for score, _ in scored)
        if best_score <= 0:
            return []

        best_page = min(page.page_number for score, page in scored if score == best_score)
        return [
            page
            for score, page in scored
            if score >= 2 and best_page <= page.page_number <= best_page + 2
        ]

    def _statement_segment_score(self, statement_type: StatementType, segment: str, header_blob: str) -> int:
        lowered = segment.lower()
        score = 3
        score += sum(2 for hint in STATEMENT_BODY_HINTS[statement_type] if hint in lowered)
        duplicate_title_hits = sum(lowered.count(title) for title in EXACT_STATEMENT_TITLES[statement_type])
        if duplicate_title_hits > 1:
            score -= 3
        if "independent auditor" in lowered or "report on the audit" in lowered:
            score -= 4
        if "notes to consolidated financial statements" in lowered:
            score -= 3
        if "business notice report governance statements information report" in lowered:
            score -= 1
        if "as per our report of even date" in lowered:
            score += 1
        if statement_type == "balance_sheet" and "for the year ended" in header_blob:
            score -= 1
        if statement_type in {"profit_and_loss", "cash_flow"} and "as at" in header_blob and "for the year ended" not in header_blob:
            score -= 1
        return score

    def _parse_statement_pages(
        self,
        statement_type: StatementType,
        pages: list[PageExtraction],
    ) -> StatementData:
        if not pages:
            return StatementData(
                statement_type=statement_type,
                title=statement_type.replace("_", " ").title(),
                years=[],
                rows=[],
                source_pages=[],
                confidence=0.0,
            )

        title = next(
            (
                line.strip()
                for page in pages
                for line in page.text.splitlines()
                if "consolidated" in line.lower() and any(word in line.lower() for word in ("balance", "profit", "cash"))
            ),
            statement_type.replace("_", " ").title(),
        )
        lines = [
            " ".join(line.split()).strip()
            for page in pages
            for line in page.text.splitlines()
            if line.strip()
        ]
        return self._parse_statement_lines(
            statement_type=statement_type,
            title=title,
            lines=lines,
            source_pages=[page.page_number for page in pages],
            confidence=0.97,
        )

    def _parse_statement_lines(
        self,
        statement_type: StatementType,
        title: str,
        lines: list[str],
        source_pages: list[int],
        confidence: float,
    ) -> StatementData:
        years = self._extract_fiscal_years("\n".join(lines))
        years = years[-2:] if len(years) >= 2 else years
        rows: list[StatementRow] = []
        seen: set[str] = set()
        line_index = 0
        while line_index < len(lines):
            parsed, consumed = self._parse_statement_row(lines, line_index, years)
            if not parsed:
                line_index += max(consumed, 1)
                continue
            key = parsed.item.lower()
            if key in seen:
                line_index += max(consumed, 1)
                continue
            seen.add(key)
            rows.append(parsed)
            line_index += max(consumed, 1)

        return StatementData(
            statement_type=statement_type,
            title=title,
            years=years,
            rows=rows,
            source_pages=source_pages,
            confidence=confidence if rows else 0.0,
            row_count=len(rows),
        )

    def _parse_statement_row(
        self,
        lines: list[str],
        start_index: int,
        years: list[str],
    ) -> tuple[StatementRow | None, int]:
        direct = self._parse_statement_line(lines[start_index], years)
        if direct:
            return direct, 1

        wrapped = self._parse_wrapped_statement_line(lines, start_index, years)
        if wrapped:
            return wrapped

        label_only = self._parse_label_only_statement_line(lines[start_index], years)
        if label_only:
            return label_only, 1

        return None, 1

    def _years_from_statement_pages(self, pages: list[PageExtraction]) -> list[str]:
        text = "\n".join(page.text for page in pages)
        years = self._extract_fiscal_years(text)
        return years[-2:] if len(years) >= 2 else years

    def _extract_fiscal_years(self, text: str) -> list[str]:
        ordered: list[str] = []
        for pattern in FISCAL_YEAR_PATTERNS:
            for match in pattern.findall(text):
                groups = match if isinstance(match, tuple) else (match,)
                for raw_year in groups:
                    normalized = self._normalize_year_token(raw_year)
                    if normalized and normalized not in ordered:
                        ordered.append(normalized)
        filtered = [year for year in ordered if 2020 <= int(year) <= 2030]
        return filtered

    def _normalize_year_token(self, token: str) -> str | None:
        value = token.strip()
        if not value.isdigit():
            return None
        if len(value) == 2:
            year = 2000 + int(value)
        elif len(value) == 4:
            year = int(value)
        else:
            return None
        if 2020 <= year <= 2030:
            return str(year)
        return None

    def _parse_statement_line(self, line: str, years: list[str]) -> StatementRow | None:
        cleaned = " ".join(line.split()).strip()
        if not cleaned:
            return None
        lowered = cleaned.lower()
        if lowered.startswith(("company overview", "cin :", "(inr crores)", "the accompanying notes", "as per our report")):
            return None
        if lowered.startswith(("consolidated balance sheet", "consolidated statement of profit and loss", "consolidated statement of cash flows")):
            return None
        if lowered.startswith(("as at march 31", "for the year ended march 31", "march 31, 2025", "march 31, 2024")):
            return None
        if lowered in {"cash and cash equivalents comprise of :", "balances with banks:"}:
            return None
        if re.match(r"^(sd/-|place:|date:)", lowered):
            return None

        tail_tokens = self._extract_tail_value_tokens(cleaned)
        if tail_tokens:
            token_count = len(cleaned.split())
            item_part = " ".join(cleaned.split()[: token_count - len(tail_tokens)]).strip(" :-")
            selected = tail_tokens[-2:]
        else:
            return None

        item_part = re.sub(r"\b[0-9]{1,2}(?:\([a-z]\))?$", "", item_part).strip(" .:-")
        item_part = re.sub(r"\((?:[IVX]+|[A-Z]+)\)$", "", item_part).strip(" .:-")
        if len(item_part) < 3:
            return None
        if YEAR_REGEX.search(item_part):
            return None
        if item_part.lower() in {
            "particulars note as at as at",
            "particulars note for the year ended for the year ended",
            "particulars as at as at",
            "particulars for the year ended for the year ended",
        }:
            return None

        resolved_years = years if len(years) >= 2 else ["Year 1", "Year 2"]
        value_map = {year: self._parse_number(raw) for year, raw in zip(resolved_years, selected)}
        raw_map = {year: raw for year, raw in zip(resolved_years, selected)}
        return StatementRow(item=item_part, values=value_map, raw_values=raw_map)

    def _parse_wrapped_statement_line(
        self,
        lines: list[str],
        start_index: int,
        years: list[str],
    ) -> tuple[StatementRow | None, int] | None:
        base = " ".join(lines[start_index].split()).strip()
        if not base or self._is_ignorable_statement_text(base):
            return None
        if self._extract_tail_value_tokens(base):
            return None
        if self._parse_label_only_statement_line(base, years):
            return None

        label_parts = [self._strip_statement_label(base)]
        numeric_line: str | None = None
        consumed = 1
        for index in range(start_index + 1, min(len(lines), start_index + 5)):
            candidate = " ".join(lines[index].split()).strip()
            if not candidate or self._is_ignorable_statement_text(candidate):
                break
            if self._is_numeric_only_line(candidate):
                numeric_line = candidate
                consumed = index - start_index + 1
                for tail_index in range(index + 1, min(len(lines), index + 3)):
                    tail_candidate = " ".join(lines[tail_index].split()).strip()
                    if self._can_be_label_continuation(tail_candidate):
                        label_parts.append(self._strip_statement_label(tail_candidate))
                        consumed = tail_index - start_index + 1
                    else:
                        break
                break
            if self._can_be_label_continuation(candidate):
                label_parts.append(self._strip_statement_label(candidate))
                consumed = index - start_index + 1
                continue
            break

        if not numeric_line:
            return None

        label = " ".join(part for part in label_parts if part).strip()
        if not label:
            return None

        resolved_years = years if len(years) >= 2 else ["Year 1", "Year 2"]
        selected = self._extract_tail_value_tokens(numeric_line)[-2:]
        value_map = {year: self._parse_number(raw) for year, raw in zip(resolved_years, selected)}
        raw_map = {year: raw for year, raw in zip(resolved_years, selected)}
        return StatementRow(item=label, values=value_map, raw_values=raw_map), consumed

    def _parse_label_only_statement_line(self, line: str, years: list[str]) -> StatementRow | None:
        cleaned = " ".join(line.split()).strip()
        if not cleaned or self._is_ignorable_statement_text(cleaned):
            return None

        stripped = self._strip_statement_label(cleaned)
        lowered = stripped.lower().strip(" :")
        if lowered in {
            "income",
            "expenses",
            "tax expense",
            "other comprehensive income / (loss)",
            "(a) items that will not be reclassified to profit or loss",
            "(b) items that will be reclassified to profit or loss",
            "assets",
            "equity and liabilities",
            "equity",
            "liabilities",
            "cash flows from operating activities",
            "cash flows from investing activities",
            "cash flows from financing activities",
            "movements in working capital",
            "current assets",
            "non-current assets",
            "current liabilities",
            "non-current liabilities",
            "financial assets",
            "financial liabilities",
            "fixed assets",
        }:
            resolved_years = years if len(years) >= 2 else ["Year 1", "Year 2"]
            return StatementRow(
                item=stripped,
                values={year: None for year in resolved_years},
                raw_values={year: "" for year in resolved_years},
            )
        return None

    def _collect_candidates(self, pages: list[PageExtraction]) -> list[RawTableCandidate]:
        candidates: list[RawTableCandidate] = []
        for page in pages:
            page_text = page.text.lower()
            if any(hint in page_text for hint in STANDALONE_HINTS) and "consolidated" not in page_text:
                continue
            for statement_type, keywords in STATEMENT_KEYWORDS.items():
                score = 0.0
                score += sum(2.0 for keyword in keywords if keyword in page_text)
                score += 1.5 if any(hint in page_text for hint in CONSOLIDATED_HINTS) else 0
                if score <= 0:
                    continue
                tables = page.tables or self._extract_page_tables(page)
                for table in tables:
                    normalized = self._normalize_table_grid(table)
                    if len(normalized) < 2:
                        continue
                    candidates.append(
                        RawTableCandidate(
                            statement_type=statement_type,
                            title=self._guess_table_title(statement_type, page.text),
                            page_number=page.page_number,
                            dataframe_rows=normalized,
                            score=score + self._table_score(normalized),
                        )
                    )

                # Fallback text parsing when table extraction misses structure.
                text_rows = self._text_rows_from_page(page.text)
                if text_rows:
                    candidates.append(
                        RawTableCandidate(
                            statement_type=statement_type,
                            title=self._guess_table_title(statement_type, page.text),
                            page_number=page.page_number,
                            dataframe_rows=text_rows,
                            score=score + self._table_score(text_rows) * 0.7,
                        )
                    )
        return candidates

    def _extract_page_tables(self, page: PageExtraction) -> list[list[list[str]]]:
        return []

    def _normalize_table_grid(self, table: list[list[str | None]]) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in table:
            cleaned = [self._clean_cell(cell) for cell in row if self._clean_cell(cell)]
            if cleaned:
                rows.append(cleaned)
        return rows

    def _text_rows_from_page(self, text: str) -> list[list[str]]:
        rows: list[list[str]] = []
        for line in text.splitlines():
            cleaned = " ".join(line.split()).strip()
            if not cleaned:
                continue
            match = re.match(r"^(.*?)(\(?[-+]?\d[\d,.\s]*\)?(?:\s+\(?[-+]?\d[\d,.\s]*\)?){1,5})$", cleaned)
            if not match:
                continue
            label = match.group(1).strip(" .:-")
            values = [token.strip() for token in re.split(r"\s{2,}|\t", match.group(2).strip()) if token.strip()]
            if label and len(values) >= 2:
                rows.append([label, *values])
        return rows

    def _build_statements(
        self,
        candidates: list[RawTableCandidate],
        detected_years: list[str],
    ) -> dict[StatementType, StatementData]:
        grouped: dict[StatementType, list[RawTableCandidate]] = defaultdict(list)
        for candidate in candidates:
            grouped[candidate.statement_type].append(candidate)

        statements: dict[StatementType, StatementData] = {}
        for statement_type in ("balance_sheet", "profit_and_loss", "cash_flow"):
            options = sorted(grouped.get(statement_type, []), key=lambda item: item.score, reverse=True)
            statement = self._best_statement(statement_type, options, detected_years)
            statements[statement_type] = statement
        return statements

    def _best_statement(
        self,
        statement_type: StatementType,
        candidates: list[RawTableCandidate],
        detected_years: list[str],
    ) -> StatementData:
        if not candidates:
            return StatementData(
                statement_type=statement_type,
                title=statement_type.replace("_", " ").title(),
                years=detected_years,
                rows=[],
                source_pages=[],
                confidence=0.0,
                row_count=0,
            )

        merged_rows: list[list[str]] = []
        source_pages: list[int] = []
        title = candidates[0].title
        for candidate in candidates[:3]:
            merged_rows.extend(candidate.dataframe_rows)
            source_pages.append(candidate.page_number)

        years = detected_years[-2:] if len(detected_years) >= 2 else detected_years
        rows = self._fallback_rows_to_statement_rows(merged_rows, years)
        confidence = min(0.99, max(candidate.score for candidate in candidates) / 8.0)
        return StatementData(
            statement_type=statement_type,
            title=title,
            years=years,
            rows=rows,
            source_pages=sorted(set(source_pages)),
            confidence=round(confidence, 2),
            row_count=len(rows),
        )

    def _fallback_rows_to_statement_rows(self, rows_input: list[list[str]], years: list[str]) -> list[StatementRow]:
        rows: list[StatementRow] = []
        for raw_row in rows_input:
            if not raw_row:
                continue
            item = self._clean_cell(str(raw_row[0]))
            if not item or YEAR_REGEX.search(item) or item.lower() in {"particulars", "notes"}:
                continue
            numeric_candidates = [self._clean_cell(str(value)) for value in raw_row[1:]]
            numeric_candidates = [value for value in numeric_candidates if value]
            parsed = [value for value in numeric_candidates if self._looks_numeric(value)]
            if len(parsed) < 2:
                continue
            selected = parsed[-len(years) :]
            value_map = {year: self._parse_number(raw) for year, raw in zip(years, selected)}
            raw_map = {year: raw for year, raw in zip(years, selected)}
            rows.append(StatementRow(item=item, values=value_map, raw_values=raw_map))
        deduped: list[StatementRow] = []
        seen: set[str] = set()
        for row in rows:
            key = row.item.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        return deduped

    def _looks_numeric(self, value: str) -> bool:
        compact = value.replace(" ", "")
        return bool(NUMERIC_TOKEN_REGEX.match(compact))

    def _extract_tail_value_tokens(self, text: str) -> list[str]:
        accepted_dash = {"-", "--", "—"}
        tokens = [token.strip() for token in text.split() if token.strip()]
        tail: list[str] = []
        for token in reversed(tokens):
            if self._looks_numeric(token) or token in accepted_dash:
                tail.append(token)
                continue
            if tail:
                break
        extracted = list(reversed(tail))
        return extracted if len(extracted) >= 2 else []

    def _is_numeric_only_line(self, text: str) -> bool:
        tokens = [token.strip() for token in text.split() if token.strip()]
        if len(tokens) < 2:
            return False
        accepted_dash = {"-", "--", "—"}
        return all(self._looks_numeric(token) or token in accepted_dash for token in tokens)

    def _can_be_label_continuation(self, text: str) -> bool:
        if not text or self._is_ignorable_statement_text(text):
            return False
        if self._extract_tail_value_tokens(text):
            return False
        lowered = text.lower()
        if lowered.startswith(("particulars", "march 31", "for the year ended", "as at")):
            return False
        return True

    def _strip_statement_label(self, text: str) -> str:
        stripped = re.sub(r"\b[0-9]{1,2}(?:\([a-z]\))?$", "", text).strip(" .:-")
        stripped = re.sub(r"\((?:[IVX]+|[A-Z]+)\)$", "", stripped).strip(" .:-")
        return stripped

    def _is_ignorable_statement_text(self, text: str) -> bool:
        lowered = text.lower()
        return lowered.startswith((
            "company overview",
            "management discussion and analysis",
            "cin :",
            "(inr crores)",
            "the accompanying notes",
            "as per our report",
            "for the year ended march 31",
            "as at march 31",
            "march 31, 2025",
            "march 31, 2024",
            "particulars note for the year ended for the year ended",
            "particulars note as at as at",
            "particulars for the year ended for the year ended",
            "particulars as at as at",
        ))

    def _parse_number(self, raw: str) -> float | None:
        text = raw.replace(" ", "").replace(",", "")
        if text in {"", "-", "na", "n/a"}:
            return None
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1]
        try:
            value = float(text)
        except ValueError:
            return None
        return -value if negative else value

    def _table_score(self, rows: list[list[str]]) -> float:
        row_bonus = min(len(rows) / 10.0, 2.0)
        numeric_rows = 0
        for row in rows:
            if sum(1 for cell in row[1:] if self._looks_numeric(cell)) >= 2:
                numeric_rows += 1
        return row_bonus + min(numeric_rows / 8.0, 2.0)

    def _guess_table_title(self, statement_type: StatementType, page_text: str) -> str:
        lowered = page_text.lower()
        for keyword in STATEMENT_KEYWORDS[statement_type]:
            if keyword in lowered:
                return keyword.title()
        return statement_type.replace("_", " ").title()

    def _clean_cell(self, value: str | None) -> str:
        if value is None:
            return ""
        return " ".join(str(value).replace("\n", " ").split()).strip()
