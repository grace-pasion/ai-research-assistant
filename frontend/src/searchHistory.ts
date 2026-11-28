import type { CrossProjectSearchRecord, Project, SearchQueryHistoryRecord } from "./types";

export function crossProjectSearchParams(record: CrossProjectSearchRecord): URLSearchParams {
  const params = new URLSearchParams({ q: record.query_text });
  for (const [key, value] of Object.entries(record.filters)) {
    params.set(key, String(value));
  }
  if (!params.has("limit")) params.set("limit", "50");
  return params;
}

export function crossProjectSearchActiveFilterLabels(
  searchParams: string,
  projects: Pick<Project, "project_id" | "project_name">[],
): string[] {
  const params = new URLSearchParams(searchParams);
  const labels: string[] = [];
  const query = params.get("q")?.trim();
  const projectId = params.get("project_id");
  const sourceType = params.get("source_type");
  const author = params.get("author")?.trim();
  const year = params.get("year");
  const tag = params.get("tag")?.trim();

  if (query) labels.push(`Search: ${query}`);
  if (projectId) {
    const projectName = projects.find((project) => project.project_id === projectId)?.project_name;
    labels.push(`Project: ${projectName ?? projectId}`);
  }
  if (sourceType) {
    const sourceLabel = sourceType === "paper"
      ? "Papers"
      : sourceType === "document" ? "Documents" : sourceType;
    labels.push(`Source type: ${sourceLabel}`);
  }
  if (author) labels.push(`Author: ${author}`);
  if (year) labels.push(`Year: ${year}`);
  if (tag) labels.push(`Tag: ${tag}`);
  return labels;
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
