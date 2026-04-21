function formatValue(value) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return new Intl.NumberFormat("en-IN", {
    maximumFractionDigits: 2,
  }).format(value);
}

export default function StatementTable({ title, statement }) {
  const years = statement?.years || [];
  const rows = statement?.rows || [];
  const checks = statement?.totals_check || [];

  return (
    <section className="panel statement-panel">
      <div className="statement-header">
        <div>
          <span className="eyebrow">Structured output</span>
          <h3>{title}</h3>
        </div>
        <span className="confidence-pill">Confidence {Math.round((statement?.confidence || 0) * 100)}%</span>
      </div>
      <p className="validation-summary">
        {rows.length} aligned line items, {checks.filter((check) => check.status === "matched").length}/
        {checks.length} total checks matched
      </p>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Item</th>
              {years.map((year) => (
                <th key={year}>{year}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={Math.max(years.length + 1, 2)}>No rows extracted.</td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.item}>
                  <td>{row.item}</td>
                  {years.map((year) => (
                    <td key={`${row.item}-${year}`}>{formatValue(row.values?.[year])}</td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {checks.length ? (
        <div className="checks-wrap">
          <h4>Total validation</h4>
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Year</th>
                <th>Reported</th>
                <th>Calculated</th>
                <th>Diff</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {checks.slice(0, 10).map((check) => (
                <tr key={`${check.item}-${check.year}`}>
                  <td>{check.item}</td>
                  <td>{check.year}</td>
                  <td>{formatValue(check.reported_total)}</td>
                  <td>{formatValue(check.calculated_total)}</td>
                  <td>{formatValue(check.difference)}</td>
                  <td>{check.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
