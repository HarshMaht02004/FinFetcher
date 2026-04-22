const API_BASE_URL = import.meta.env.VITE_API_URL;

async function handleResponse(response) {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Request failed");
  }
  return response;
}

export async function uploadReport(files) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  const response = await handleResponse(
    await fetch(`${API_BASE_URL}/upload`, {
      method: "POST",
      body: formData,
    })
  );
  return response.json();
}

export async function fetchExtraction(reportId) {
  const response = await handleResponse(
    await fetch(`${API_BASE_URL}/extract?report_id=${encodeURIComponent(reportId)}`)
  );
  return response.json();
}

export async function queryReport(reportId, question) {
  const response = await handleResponse(
    await fetch(`${API_BASE_URL}/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ report_id: reportId, question }),
    })
  );
  return response.json();
}

export function downloadReport(reportId) {
  window.open(`${API_BASE_URL}/download?report_id=${encodeURIComponent(reportId)}`, "_blank");
}
