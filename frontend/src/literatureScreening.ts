import type { Paper, PaperScreeningDecision, ScreeningExclusionReason } from "./types";
import {
  hasLibraryMetadataFilters,
  libraryMetadataFilterLabels,
  type LibraryMetadataFilters,
} from "./libraryMetadata";

export type ScreeningStatusFilter = Paper["screening_status"] | "all";
export type ScreeningSort = "saved" | "title" | "year_desc" | "year_asc";
export type ScreeningYearFilter = number | "all" | "unknown";

export function hasScreeningFilters(
  status: ScreeningStatusFilter,
  query: string,
  year: ScreeningYearFilter,
  metadataFilters: LibraryMetadataFilters,
): boolean {
  return status !== "all"
    || query.trim().length > 0
    || year !== "all"
    || hasLibraryMetadataFilters(metadataFilters);
}

export function screeningFilterLabels(
  status: ScreeningStatusFilter,
  query: string,
  year: ScreeningYearFilter,
  metadataFilters: LibraryMetadataFilters,
): string[] {
  const labels: string[] = [];
  if (status !== "all") {
    const decisionLabel = {
      unread: "Unread",
      undecided: "Undecided",
      include: "Included",
      exclude: "Excluded",
    }[status];
    labels.push(`Decision: ${decisionLabel}`);
  }
  if (query.trim()) labels.push(`Search: ${query.trim()}`);
  if (year !== "all") {
    labels.push(`Publication year: ${year === "unknown" ? "Unavailable" : year}`);
  }
  return [...labels, ...libraryMetadataFilterLabels(metadataFilters)];
}

export const SCREENING_EXCLUSION_REASONS: {
  value: ScreeningExclusionReason;
  label: string;
}[] = [
  { value: "wrong_population", label: "Wrong population" },
  { value: "wrong_intervention", label: "Wrong intervention or exposure" },
  { value: "wrong_comparator", label: "Wrong comparator" },
  { value: "wrong_outcome", label: "Wrong outcome" },
  { value: "wrong_study_design", label: "Wrong study design" },
  { value: "wrong_setting", label: "Wrong setting" },
  { value: "wrong_publication_type", label: "Wrong publication type" },
  { value: "duplicate_record", label: "Duplicate record" },
  { value: "full_text_unavailable", label: "Full text unavailable" },
  { value: "other", label: "Other" },
];

export function exclusionReasonLabel(reason: ScreeningExclusionReason | null): string {
  return SCREENING_EXCLUSION_REASONS.find((item) => item.value === reason)?.label ?? "";
}

export function hasScreeningDisagreement(decisions: PaperScreeningDecision[]): boolean {
  const outcomes = new Set(decisions.map((decision) =>
    `${decision.screening_status}:${decision.screening_status === "exclude" ? decision.exclusion_reason ?? "" : ""}`,
  ));
  return outcomes.size > 1;
}

export function filterAndSortScreeningPapers(
  papers: Paper[],
  status: ScreeningStatusFilter,
  query: string,
  sort: ScreeningSort,
  year: ScreeningYearFilter = "all",
): Paper[] {
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = papers.filter((paper) => {
    if (status !== "all" && paper.screening_status !== status) return false;
    if (year === "unknown" && paper.publication_year !== null) return false;
    if (typeof year === "number" && paper.publication_year !== year) return false;
    if (!normalizedQuery) return true;
    const searchableText = [
      paper.title,
      paper.abstract ?? "",
      paper.doi ?? "",
      paper.venue ?? "",
      ...paper.authors.map((author) => author.author_name),
    ].join(" ").toLowerCase();
    return searchableText.includes(normalizedQuery);
  });

  if (sort === "saved") return filtered;
  return filtered.sort((left, right) => {
    if (sort === "title") return left.title.localeCompare(right.title);
    if (left.publication_year == null) return right.publication_year == null ? 0 : 1;
    if (right.publication_year == null) return -1;
    return sort === "year_desc"
      ? right.publication_year - left.publication_year
      : left.publication_year - right.publication_year;
  });
}
