import { useState } from "react";
import ChatPanel from "./components/ChatPanel";
import StatementTable from "./components/StatementTable";
import UploadPanel from "./components/UploadPanel";
import { downloadReport, fetchExtraction, queryReport, uploadReport } from "./lib/api";

const API_URL = import.meta.env.VITE_API_URL;

async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_URL}/upload`, {
    method: "POST",
    body: formData,
  });

  return await res.json();
}

const statementLabels = {
  balance_sheet: "Balance Sheet",
  profit_and_loss: "Profit & Loss Statement",
  cash_flow: "Cash Flow Statement",
};

export default function App() {
  const [files, setFiles] = useState([]);
  const [reportId, setReportId] = useState("");
  const [extraction, setExtraction] = useState(null);
  const [messages, setMessages] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isQuerying, setIsQuerying] = useState(false);
  const [error, setError] = useState("");

  async function handleUpload() {
    if (!files.length) {
      return;
    }

    setIsUploading(true);
    setError("");
    try {
      const upload = await uploadReport(files);
      setReportId(upload.report_id);
      const extracted = await fetchExtraction(upload.report_id);
      setExtraction(extracted);
      setMessages([
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content:
            "Reports processed successfully. You can review the aligned multi-year financial statements below or start asking grounded questions about the consolidated reports.",
        },
      ]);
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setIsUploading(false);
    }
  }

  async function handleQuestion(question) {
    setIsQuerying(true);
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", content: question },
    ]);

    try {
      const response = await queryReport(reportId, question);
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: "assistant", content: response.answer },
      ]);
    } catch (queryError) {
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `Unable to answer the question: ${queryError.message}`,
        },
      ]);
    } finally {
      setIsQuerying(false);
    }
  }

  return (
    <main className="app-shell">
      <div className="ambient-orb ambient-orb-left" />
      <div className="ambient-orb ambient-orb-right" />

      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow">Financial AI Workbench</span>
          <h1>Annual report extraction and RAG analysis in one workflow.</h1>
          <p>
            Upload a company annual report, convert consolidated statements into
            structured tables, export them to Excel, and ask grounded financial
            questions against the report context.
          </p>

          <div className="hero-actions">
            <div className="hero-chip">
              <strong>Three core outputs</strong>
              <span>Balance Sheet, P&amp;L, Cash Flow</span>
            </div>
            <div className="hero-chip">
              <strong>Interactive review</strong>
              <span>Validation, Q&amp;A, Excel export</span>
            </div>
          </div>
        </div>

        <div className="hero-card">
          <div className="metric">
            <strong>{reportId ? "Ready" : "Idle"}</strong>
            <span>Processing status</span>
          </div>
          <div className="metric">
            <strong>{extraction?.metadata?.years?.join(" / ") || "Multi-Y"}</strong>
            <span>Year coverage</span>
          </div>
          <div className="metric">
            <strong>{extraction?.metadata?.source_reports || 0}</strong>
            <span>Reports merged</span>
          </div>
          <div className="metric metric-accent">
            <strong>{extraction ? "Live workspace" : "Awaiting upload"}</strong>
            <span>Extraction canvas</span>
          </div>
        </div>
      </section>

      <section className="spotlight-strip">
        <article className="spotlight-card">
          <span className="eyebrow">Experience</span>
          <h3>Review statements in a calmer, brighter workspace.</h3>
          <p>Designed for long financial reading sessions with high contrast tables and softer surfaces.</p>
        </article>
        <article className="spotlight-card">
          <span className="eyebrow">Workflow</span>
          <h3>Upload, validate, question, export.</h3>
          <p>The interface keeps the full extraction workflow visible instead of burying key actions.</p>
        </article>
      </section>

      <section className="top-grid">
        <UploadPanel
          files={files}
          isUploading={isUploading}
          onFileChange={(event) => setFiles(Array.from(event.target.files || []))}
          onUpload={handleUpload}
        />

        <ChatPanel
          reportId={reportId}
          messages={messages}
          isQuerying={isQuerying}
          onSend={handleQuestion}
        />
      </section>

      {error ? <div className="error-banner">{error}</div> : null}

      {extraction ? (
        <>
          <section className="panel meta-panel">
            <div className="panel-heading">
              <span className="eyebrow">Report summary</span>
              <h2>{extraction.metadata.company_name || extraction.metadata.filename}</h2>
            </div>

            <div className="meta-actions">
              <div>
                <span className="meta-label">Report ID</span>
                <strong>{extraction.report_id}</strong>
              </div>
              <div>
                <span className="meta-label">Years</span>
                <strong>{extraction.metadata.years.join(" / ") || "Not detected"}</strong>
              </div>
              <div>
                <span className="meta-label">Source reports</span>
                <strong>{extraction.metadata.source_reports}</strong>
              </div>
              <button className="secondary-button" onClick={() => downloadReport(extraction.report_id)}>
                Download Excel
              </button>
            </div>

            {extraction.metadata.filenames?.length ? (
              <div className="file-pill-row">
                {extraction.metadata.filenames.map((name) => (
                  <span className="file-pill" key={name}>
                    {name}
                  </span>
                ))}
              </div>
            ) : null}

            <div className="insight-grid">
              {(extraction.insights || []).map((insight) => (
                <article className="insight-card" key={insight.title}>
                  <h3>{insight.title}</h3>
                  <p>{insight.content}</p>
                </article>
              ))}
            </div>
          </section>

          <section className="statement-grid">
            {Object.entries(statementLabels).map(([key, label]) => (
              <StatementTable key={key} title={label} statement={extraction.statements[key]} />
            ))}
          </section>
        </>
      ) : null}
    </main>
  );
}
