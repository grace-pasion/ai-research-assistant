export const PAPER_ABSTRACT_PREVIEW_LENGTH = 500;

export type PaperAbstractContent = {
  text: string;
  preview: string;
  hasMore: boolean;
};

export function preparePaperAbstract(abstract: string | null): PaperAbstractContent {
  const text = (abstract ?? "")
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<\/(?:p|div|li|h[1-6])\s*>/gi, " ")
    .replace(/<[^>]*>/g, "")
    .replace(/\s+/g, " ")
    .trim();
  const characters = Array.from(text);
  return {
    text,
    preview: characters.slice(0, PAPER_ABSTRACT_PREVIEW_LENGTH).join(""),
    hasMore: characters.length > PAPER_ABSTRACT_PREVIEW_LENGTH,
  };
}
