import type { Paper } from "./types";

export type ScreeningStatusFilter = Paper["screening_status"] | "all";
export type ScreeningSort = "saved" | "title" | "year_desc" | "year_asc";

export function filterAndSortScreeningPapers(
  papers: Paper[],
  status: ScreeningStatusFilter,
  query: string,
  sort: ScreeningSort,
): Paper[] {
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = papers.filter((paper) => {
    if (status !== "all" && paper.screening_status !== status) return false;
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
