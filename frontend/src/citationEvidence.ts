export type CitationRange = { start: number; end: number };

export function findCitationRange(text: string, excerpt: string | null): CitationRange | null {
  if (!excerpt) return null;
  const stringStart = text.indexOf(excerpt);
  if (stringStart < 0) return null;
  const start = Array.from(text.slice(0, stringStart)).length;
  return { start, end: start + Array.from(excerpt).length };
}
