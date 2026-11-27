import type { Paper } from "./types";

const STOP_WORDS = new Set(
  "a an and are as at be by for from in into is it of on or that the their this to was were with".split(" "),
);

export type PaperSimilarityMatch = {
  paper: Paper;
  kind: "possible_duplicate" | "related";
  reason: string;
  similarity: number;
};

function normalizeText(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function normalizeDoi(value: string | null): string | null {
  if (!value) return null;
  const doi = value
    .trim()
    .replace(/^doi\s*:\s*/i, "")
    .replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "")
    .replace(/[.,;]+$/, "")
    .toLowerCase();
  return /^10\.\d{4,9}\/\S+$/.test(doi) ? doi : null;
}

function paperDoi(paper: Paper): string | null {
  return normalizeDoi(paper.doi) ?? normalizeDoi(paper.paper_url);
}

function titleTokens(title: string): Set<string> {
  return new Set(
    normalizeText(title)
      .split(" ")
      .filter((token) => token.length > 2 && !STOP_WORDS.has(token)),
  );
}

function characterTrigrams(title: string): Set<string> {
  const compact = normalizeText(title).replace(/\s/g, "");
  if (!compact) return new Set();
  if (compact.length < 3) return new Set([compact]);
  return new Set(Array.from({ length: compact.length - 2 }, (_, index) =>
    compact.slice(index, index + 3),
  ));
}

function diceSimilarity(left: Set<string>, right: Set<string>): number {
  if (!left.size || !right.size) return 0;
  let shared = 0;
  for (const value of left) {
    if (right.has(value)) shared += 1;
  }
  return (2 * shared) / (left.size + right.size);
}

function compareTitles(left: string, right: string) {
  const normalizedLeft = normalizeText(left);
  const normalizedRight = normalizeText(right);
  const leftTokens = titleTokens(left);
  const rightTokens = titleTokens(right);
  let sharedTokens = 0;
  for (const token of leftTokens) {
    if (rightTokens.has(token)) sharedTokens += 1;
  }

  return {
    exact: normalizedLeft.length > 0 && normalizedLeft === normalizedRight,
    similarity: Math.max(
      diceSimilarity(leftTokens, rightTokens),
      diceSimilarity(characterTrigrams(left), characterTrigrams(right)),
    ),
    sharedTokens,
  };
}

export function findPaperSimilarityMatches(
  candidate: Paper,
  savedPapers: Paper[],
): PaperSimilarityMatch[] {
  const candidateDoi = paperDoi(candidate);
  return savedPapers.flatMap((paper): PaperSimilarityMatch[] => {
    if (paper.paper_id === candidate.paper_id) return [];

    const doiMatches = candidateDoi !== null && candidateDoi === paperDoi(paper);
    const title = compareTitles(candidate.title, paper.title);
    if (doiMatches) {
      return [{ paper, kind: "possible_duplicate", reason: "Same DOI", similarity: 1 }];
    }
    if (title.exact) {
      return [{
        paper,
        kind: "possible_duplicate",
        reason: "Title matches after normalizing punctuation, case, and accents",
        similarity: 1,
      }];
    }
    if (title.similarity >= 0.84) {
      return [{
        paper,
        kind: "possible_duplicate",
        reason: "Title is highly similar",
        similarity: title.similarity,
      }];
    }
    if (title.sharedTokens >= 2 && title.similarity >= 0.35) {
      return [{
        paper,
        kind: "related",
        reason: "Titles share key terms",
        similarity: title.similarity,
      }];
    }
    return [];
  }).sort((left, right) =>
    Number(right.kind === "possible_duplicate") - Number(left.kind === "possible_duplicate")
      || right.similarity - left.similarity
      || left.paper.title.localeCompare(right.paper.title),
  );
}
