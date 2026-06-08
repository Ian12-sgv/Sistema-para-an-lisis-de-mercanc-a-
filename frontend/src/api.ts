import type { DashboardSummary, QueryDefinition, QueryResult, UnifiedQueryResult } from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...Object.fromEntries(new Headers(options?.headers ?? {})),
  };

  if (options?.body != null && !headers["content-type"] && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_URL}${path}`, {
    headers,
    ...options,
  });

  if (!response.ok) {
    const detail = await response.text();
    let message = detail || `HTTP ${response.status}`;

    try {
      const parsed = JSON.parse(detail) as { detail?: unknown };
      message = typeof parsed.detail === "string" ? parsed.detail : message;
    } catch {
      // Keep the raw response when the server did not return JSON.
    }

    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export function fetchQueries() {
  return request<QueryDefinition[]>("/api/queries");
}

export function runQuery(queryId: string, parameters: Record<string, string> = {}, page = 1, pageSize = 200) {
  return request<QueryResult>("/api/queries/run", {
    method: "POST",
    body: JSON.stringify({ queryId, parameters, page, pageSize }),
  });
}

export function unifyQueries(queryIds: string[], parameters: Record<string, string> = {}) {
  return request<UnifiedQueryResult>("/api/queries/unify", {
    method: "POST",
    body: JSON.stringify({ queryIds, parameters }),
  });
}

export function fetchDashboardSummary(parameters: Record<string, string> = {}) {
  return request<DashboardSummary>("/api/queries/dashboard", {
    method: "POST",
    body: JSON.stringify({ parameters }),
  });
}
