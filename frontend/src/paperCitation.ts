import type { Paper } from "./types";

type CitationPaper = Pick<
  Paper,
  "title" | "authors" | "publication_year" | "doi" | "paper_url" | "venue"
>;

export async function copyTextToClipboard(value: string): Promise<void> {
  const clipboard = typeof navigator === "undefined" ? undefined : navigator.clipboard;
  if (!clipboard?.writeText) {
    throw new Error("Clipboard access is unavailable in this browser.");
  }
  await clipboard.writeText(value);
}

function normalizeDoiForCopy(value: string | null | undefined): string | null {
  const doi = value
    ?.trim()
    .replace(/^doi\s*:\s*/i, "")
    .replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "")
    .replace(/[.,;]+$/, "");
  return doi || null;
}

export function paperDoiForClipboard(
  paper: Pick<Paper, "doi" | "paper_url">,
): string | null {
  const doi = normalizeDoiForCopy(paper.doi);
  if (doi) return doi;
  if (!/^https?:\/\/(?:dx\.)?doi\.org\//i.test(paper.paper_url ?? "")) return null;
  return normalizeDoiForCopy(paper.paper_url);
}

export function formatPaperCitation(paper: CitationPaper): string {
  const authors = paper.authors.map((author) => author.author_name.trim()).filter(Boolean);
  const authorText = authors.length === 1
    ? authors[0]
    : authors.length === 2
      ? `${authors[0]} & ${authors[1]}`
      : authors.length > 2
        ? `${authors.slice(0, -1).join(", ")}, & ${authors.at(-1)}`
        : "";
  const year = paper.publication_year ?? "n.d.";
  const title = paper.title.trim();
  const citation = authorText
    ? `${authorText}. (${year}). ${title}.`
    : `${title}. (${year}).`;
  const venue = paper.venue?.trim();
  const doi = paperDoiForClipboard(paper);
  const link = doi ? `https://doi.org/${doi}` : paper.paper_url?.trim();
  return [citation, venue ? `${venue}.` : "", link ?? ""].filter(Boolean).join(" ");
}
