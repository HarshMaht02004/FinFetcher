export default function UploadPanel({ files, isUploading, onFileChange, onUpload }) {
  return (
    <section className="panel panel-upload">
      <div className="panel-heading">
        <span className="eyebrow">Pipeline</span>
        <h2>Upload one or more annual report PDFs</h2>
        <p>
          Extract consolidated Balance Sheet, Profit & Loss, and Cash Flow data,
          align line items across fiscal years, validate totals, and build a grounded
          chat index over the uploaded reports.
        </p>
      </div>

      <label className="upload-dropzone">
        <input type="file" accept="application/pdf" multiple onChange={onFileChange} />
        <span className="upload-title">
          {files.length ? `${files.length} report(s) selected` : "Choose annual report PDFs"}
        </span>
        <span className="upload-subtitle">
          Use consecutive annual reports to build one aligned multi-year financial
          view. Missing line items stay blank instead of being zero-filled.
        </span>
      </label>

      {files.length ? (
        <div className="file-pill-row">
          {files.map((file) => (
            <span className="file-pill" key={file.name}>
              {file.name}
            </span>
          ))}
        </div>
      ) : null}

      <button className="primary-button" onClick={onUpload} disabled={!files.length || isUploading}>
        {isUploading ? "Processing report..." : "Upload and analyze"}
      </button>
    </section>
  );
}
