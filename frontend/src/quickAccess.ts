import type { QuickAccessSource, QuickAccessState } from "./types";

export const QUICK_ACCESS_RECENT_LIMIT = 6;

export const EMPTY_QUICK_ACCESS: QuickAccessState = {
  recent: [],
  pinned: [],
};

function sourceKey(source: QuickAccessSource): string {
  return `${source.project_id}:${source.source_type}:${source.source_id}`;
}

function isQuickAccessSource(value: unknown): value is QuickAccessSource {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return typeof record.project_id === "string"
    && record.project_id.length > 0
    && typeof record.project_name === "string"
    && record.project_name.length > 0
    && (record.source_type === "document" || record.source_type === "paper")
    && typeof record.source_id === "string"
    && record.source_id.length > 0
    && typeof record.source_title === "string"
    && record.source_title.length > 0
    && typeof record.opened_at === "string"
    && Number.isFinite(Date.parse(record.opened_at));
}

function uniqueSources(sources: unknown[]): QuickAccessSource[] {
  const seen = new Set<string>();
  return sources.filter(isQuickAccessSource).filter((source) => {
    const key = sourceKey(source);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function parseQuickAccessState(value: string | null): QuickAccessState {
  if (value === null) return EMPTY_QUICK_ACCESS;
  const parsed: unknown = JSON.parse(value);
  if (
    parsed === null
    || typeof parsed !== "object"
    || !("recent" in parsed)
    || !("pinned" in parsed)
    || !Array.isArray(parsed.recent)
    || !Array.isArray(parsed.pinned)
  ) {
    throw new Error("Quick access items must be stored as recent and pinned lists.");
  }
  return {
    recent: uniqueSources(parsed.recent).slice(0, QUICK_ACCESS_RECENT_LIMIT),
    pinned: uniqueSources(parsed.pinned),
  };
}

export function rememberQuickAccessSource(
  current: QuickAccessState,
  source: QuickAccessSource,
): QuickAccessState {
  const key = sourceKey(source);
  return {
    recent: [
      source,
      ...current.recent.filter((item) => sourceKey(item) !== key),
    ].slice(0, QUICK_ACCESS_RECENT_LIMIT),
    pinned: current.pinned.map((item) => sourceKey(item) === key ? source : item),
  };
}

export function mergeQuickAccessSources(
  current: QuickAccessState,
  sources: QuickAccessSource[],
): QuickAccessState {
  const combined = new Map<string, QuickAccessSource>();
  for (const source of [...current.recent, ...sources]) {
    const key = sourceKey(source);
    const existing = combined.get(key);
    if (!existing || Date.parse(source.opened_at) > Date.parse(existing.opened_at)) {
      combined.set(key, source);
    }
  }
  const newestFirst = [...combined.values()].sort(
    (first, second) => Date.parse(second.opened_at) - Date.parse(first.opened_at),
  );
  const newestByKey = new Map(newestFirst.map((source) => [sourceKey(source), source]));
  return {
    recent: newestFirst.slice(0, QUICK_ACCESS_RECENT_LIMIT),
    pinned: current.pinned.map((source) => newestByKey.get(sourceKey(source)) ?? source),
  };
}

export function toggleQuickAccessPin(
  current: QuickAccessState,
  source: QuickAccessSource,
): QuickAccessState {
  const key = sourceKey(source);
  const isPinned = current.pinned.some((item) => sourceKey(item) === key);
  return {
    ...current,
    pinned: isPinned
      ? current.pinned.filter((item) => sourceKey(item) !== key)
      : [source, ...current.pinned],
  };
}
