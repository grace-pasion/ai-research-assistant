import type { CrossProjectSearchRecord, SearchQueryHistoryRecord } from "./types";

export function crossProjectSearchParams(record: CrossProjectSearchRecord): URLSearchParams {
  const params = new URLSearchParams({ q: record.query_text });
  for (const [key, value] of Object.entries(record.filters)) {
    params.set(key, String(value));
  }
  if (!params.has("limit")) params.set("limit", "50");
  return params;
}

export function literatureSearchRequest(record: SearchQueryHistoryRecord) {
  const storedLimit = record.search_filters.limit;
  return {
    query: record.query_text,
    provider: record.api_provider,
    limit:
      typeof storedLimit === "number" && Number.isInteger(storedLimit)
        ? storedLimit
        : 10,
  };
}
