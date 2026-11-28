export type LatexFormattingSuggestion = {
  sourceSnapshot: string;
  formattedSource: string;
  diff: string;
};

export function acceptLatexFormattingSuggestion(
  currentSource: string,
  suggestion: LatexFormattingSuggestion,
): string | null {
  return currentSource === suggestion.sourceSnapshot ? suggestion.formattedSource : null;
}
