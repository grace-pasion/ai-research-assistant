import type { RecentProjectSource } from "./types";

const RECENT_SOURCE_LIMIT = 6;

function isRecentProjectSource(value: unknown): value is RecentProjectSource {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (record.source_type === "document" || record.source_type === "paper")
    && typeof record.source_id === "string"
    && record.source_id.length > 0
    && typeof record.source_title === "string"
    && record.source_title.length > 0
    && typeof record.opened_at === "string"
    && Number.isFinite(Date.parse(record.opened_at));
}

export function parseRecentProjectSources(value: string | null): RecentProjectSource[] {
  if (value === null) return [];
  const parsed: unknown = JSON.parse(value);
  if (!Array.isArray(parsed)) {
    throw new Error("Recently opened sources must be stored as a list.");
  }
  return parsed.filter(isRecentProjectSource).slice(0, RECENT_SOURCE_LIMIT);
}

export function addRecentProjectSource(
  current: RecentProjectSource[],
  source: RecentProjectSource,
): RecentProjectSource[] {
  return [
    source,
    ...current.filter((item) =>
      item.source_type !== source.source_type || item.source_id !== source.source_id
    ),
  ].slice(0, RECENT_SOURCE_LIMIT);
}
