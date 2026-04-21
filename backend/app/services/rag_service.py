from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_settings
from app.models.schemas import StatementData


class RagService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _create_documents(self, report_id: str, full_text: str):
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )
        return splitter.create_documents([full_text], metadatas=[{"report_id": report_id}])

    def build_chunks(self, report_id: str, full_text: str, vector_dir: Path) -> None:
        docs = self._create_documents(report_id, full_text)
        chunk_payload = [
            {"content": doc.page_content, "metadata": doc.metadata}
            for doc in docs
        ]
        (vector_dir / "chunks.json").write_text(json.dumps(chunk_payload, indent=2), encoding="utf-8")

    def build_index(self, report_id: str, full_text: str, vector_dir: Path) -> None:
        docs = self._create_documents(report_id, full_text)
        chunk_payload = [
            {"content": doc.page_content, "metadata": doc.metadata}
            for doc in docs
        ]
        (vector_dir / "chunks.json").write_text(json.dumps(chunk_payload, indent=2), encoding="utf-8")
        if not self._llm_enabled():
            return

        embeddings = self._get_embeddings()

        if self.settings.vector_store.lower() == "chroma":
            from langchain_community.vectorstores import Chroma

            store = Chroma.from_documents(
                docs,
                embedding=embeddings,
                persist_directory=str(vector_dir),
            )
            store.persist()
            return

        from langchain_community.vectorstores import FAISS

        store = FAISS.from_documents(docs, embedding=embeddings)
        store.save_local(str(vector_dir))

    def answer_query(self, report_id: str, vector_dir: Path, question: str) -> tuple[str, list[dict[str, Any]]]:
        documents = self._retrieve_documents(vector_dir, question)
        context = "\n\n".join(doc["content"] for doc in documents)
        sources = [{"metadata": doc["metadata"], "snippet": doc["content"][:280]} for doc in documents]

        if not self._llm_enabled():
            return self._fallback_answer(question, documents), sources

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a financial analyst. Based ONLY on the provided context, answer the query. "
                    "If data is missing, say 'Not found'. Do not hallucinate.",
                ),
                ("human", "Question: {question}\n\nContext:\n{context}"),
            ]
        )
        chain = prompt | self._get_chat_model()
        result = chain.invoke({"question": question, "context": context})
        answer = getattr(result, "content", str(result))
        return answer, sources

    def generate_insights(
        self,
        statements: dict[str, StatementData],
        question_context: str,
    ) -> list[dict[str, str]]:
        derived = self._derive_statement_insights(statements)
        if all(item["content"] != "Not found" for item in derived[:3]):
            return derived

        sections = [
            ("Performance", "Summarize the key performance trend in the report."),
            ("Financial Position", "Summarize balance sheet movement and capital structure cues."),
            ("Cash Flow", "Summarize the cash flow story and liquidity clues."),
            ("Risks", "Highlight key risks or uncertainties explicitly mentioned in the report."),
        ]
        docs = [{"content": chunk} for chunk in self._chunk_text(question_context)]
        return [
            {"title": title, "content": self._fallback_answer(question, docs)}
            for title, question in sections
        ]

    def _retrieve_documents(self, vector_dir: Path, question: str) -> list[dict[str, Any]]:
        if self._llm_enabled():
            if not self.vector_store_exists(vector_dir):
                return self._retrieve_documents_without_vector_store(vector_dir, question)
            store = self._load_vector_store(vector_dir)
            retriever = store.as_retriever(search_kwargs={"k": 4})
            documents = retriever.invoke(question)
            return [{"content": doc.page_content, "metadata": doc.metadata} for doc in documents]

        return self._retrieve_documents_without_vector_store(vector_dir, question)

    def _retrieve_documents_without_vector_store(self, vector_dir: Path, question: str) -> list[dict[str, Any]]:
        chunks_path = vector_dir / "chunks.json"
        if not chunks_path.exists():
            return []
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
        scored = sorted(
            chunks,
            key=lambda chunk: self._keyword_overlap(question, chunk["content"]),
            reverse=True,
        )
        return scored[:4]

    def llm_enabled(self) -> bool:
        return self._llm_enabled()

    def vector_store_exists(self, vector_dir: Path) -> bool:
        if self.settings.vector_store.lower() == "chroma":
            return any(vector_dir.glob("*.sqlite3")) or (vector_dir / "chroma.sqlite3").exists()
        return (vector_dir / "index.faiss").exists() and (vector_dir / "index.pkl").exists()

    def _load_vector_store(self, vector_dir: Path):
        embeddings = self._get_embeddings()
        if self.settings.vector_store.lower() == "chroma":
            from langchain_community.vectorstores import Chroma

            return Chroma(persist_directory=str(vector_dir), embedding_function=embeddings)

        from langchain_community.vectorstores import FAISS

        return FAISS.load_local(
            str(vector_dir),
            embeddings=embeddings,
            allow_dangerous_deserialization=True,
        )

    def _get_embeddings(self):
        if self.settings.llm_provider.lower() == "local":
            return OpenAIEmbeddings(
                model=self.settings.local_embedding_model,
                base_url=self.settings.local_llm_base_url,
                api_key="local",
            )
        return OpenAIEmbeddings(
            model=self.settings.embedding_model,
            api_key=self.settings.openai_api_key,
        )

    def _get_chat_model(self):
        if self.settings.llm_provider.lower() == "local":
            return ChatOpenAI(
                model=self.settings.local_llm_model,
                api_key="local",
                base_url=self.settings.local_llm_base_url,
                temperature=0,
            )
        return ChatOpenAI(
            model=self.settings.llm_model,
            api_key=self.settings.openai_api_key,
            temperature=0,
        )

    def _llm_enabled(self) -> bool:
        if self.settings.llm_provider.lower() == "local":
            return bool(self.settings.local_llm_base_url)
        return bool(self.settings.openai_api_key)

    def _chunk_text(self, text: str) -> list[str]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )
        return splitter.split_text(text)

    def _keyword_overlap(self, question: str, content: str) -> int:
        tokens = {token for token in re.findall(r"[a-z0-9]+", question.lower()) if len(token) > 2}
        if not tokens:
            return 0
        lowered = content.lower()
        return sum(1 for token in tokens if token in lowered)

    def _fallback_answer(self, question: str, documents: list[dict[str, Any]]) -> str:
        if not documents:
            return "Not found"
        scored = sorted(
            documents,
            key=lambda doc: self._keyword_overlap(question, doc["content"]),
            reverse=True,
        )
        best = scored[0]["content"].strip()
        if self._keyword_overlap(question, best) == 0:
            return "Not found"
        return best[:900]

    def _derive_statement_insights(self, statements: dict[str, StatementData]) -> list[dict[str, str]]:
        return [
            {"title": "Performance", "content": self._performance_summary(statements.get("profit_and_loss"))},
            {"title": "Financial Position", "content": self._balance_sheet_summary(statements.get("balance_sheet"))},
            {"title": "Cash Flow", "content": self._cash_flow_summary(statements.get("cash_flow"))},
            {"title": "Risks", "content": self._risk_summary(statements)},
        ]

    def _performance_summary(self, statement: StatementData | None) -> str:
        return self._metric_change_summary(
            statement,
            ("revenue from operations", "total revenue", "revenue"),
            ("profit for the year", "profit after tax", "profit before tax", "ebitda"),
            "Revenue",
            "profit",
        )

    def _balance_sheet_summary(self, statement: StatementData | None) -> str:
        return self._metric_change_summary(
            statement,
            ("total assets",),
            ("total equity", "total equity and liabilities", "total liabilities"),
            "Total assets",
            "capital base",
        )

    def _cash_flow_summary(self, statement: StatementData | None) -> str:
        return self._metric_change_summary(
            statement,
            (
                "net cash generated from operating activities",
                "net cash flows from operating activities",
                "cash generated from / (used in) operations",
            ),
            (
                "cash and cash equivalents at the end of the year",
                "cash and cash equivalents at end of year",
            ),
            "Operating cash flow",
            "closing cash",
        )

    def _risk_summary(self, statements: dict[str, StatementData]) -> str:
        performance = statements.get("profit_and_loss")
        if performance:
            latest_year = performance.years[-1] if performance.years else None
            if latest_year:
                finance_costs = self._row_value(performance, ("finance costs", "finance cost"), latest_year)
                if finance_costs is not None and finance_costs < 0:
                    return f"Finance costs remain present in {latest_year}, so debt servicing should still be monitored."
        return "Not found"

    def _metric_change_summary(
        self,
        statement: StatementData | None,
        primary_labels: tuple[str, ...],
        secondary_labels: tuple[str, ...],
        primary_name: str,
        secondary_name: str,
    ) -> str:
        if not statement or len(statement.years) < 2:
            return "Not found"
        first_year = statement.years[0]
        last_year = statement.years[-1]
        first_value = self._row_value(statement, primary_labels, first_year)
        last_value = self._row_value(statement, primary_labels, last_year)
        second_last = self._row_value(statement, secondary_labels, last_year)
        if first_value is None and last_value is None and second_last is None:
            return "Not found"

        bits: list[str] = []
        if first_value is not None and last_value is not None:
            direction = "increased" if last_value >= first_value else "decreased"
            bits.append(
                f"{primary_name} {direction} from {self._format_number(first_value)} in {first_year} to {self._format_number(last_value)} in {last_year}."
            )
        if second_last is not None:
            bits.append(f"{secondary_name.capitalize()} in {last_year} was {self._format_number(second_last)}.")
        return " ".join(bits) if bits else "Not found"

    def _row_value(self, statement: StatementData, labels: tuple[str, ...], year: str) -> float | None:
        for row in statement.rows:
            normalized = " ".join(row.item.lower().replace("&", "and").split())
            if normalized in labels:
                return row.values.get(year)
        return None

    def _format_number(self, value: float) -> str:
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.2f}"
