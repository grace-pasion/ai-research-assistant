export type LibraryMetadataFields = {
  tags: string[];
  metadata: Record<string, string>;
};

export type LibraryMetadataFilters = {
  tag: string;
  metadataKey: string;
  metadataValue: string;
};

export function hasLibraryMetadataFilters(filters: LibraryMetadataFilters): boolean {
  return Object.values(filters).some((value) => value.trim().length > 0);
}

export function libraryMetadataFilterLabels(filters: LibraryMetadataFilters): string[] {
  return [
    filters.tag.trim() ? `Tag: ${filters.tag.trim()}` : "",
    filters.metadataKey.trim() ? `Metadata field: ${filters.metadataKey.trim()}` : "",
    filters.metadataValue.trim() ? `Metadata value: ${filters.metadataValue.trim()}` : "",
  ].filter(Boolean);
}

export function filterByLibraryMetadata<T extends LibraryMetadataFields>(
  items: T[],
  filters: LibraryMetadataFilters,
): T[] {
  const tag = filters.tag.trim().toLocaleLowerCase();
  const metadataKey = filters.metadataKey.trim().toLocaleLowerCase();
  const metadataValue = filters.metadataValue.trim().toLocaleLowerCase();

  return items.filter((item) => {
    if (tag && !item.tags.some((itemTag) => itemTag.toLocaleLowerCase() === tag)) return false;
    const metadataEntry = Object.entries(item.metadata).find(
      ([key]) => !metadataKey || key.toLocaleLowerCase() === metadataKey,
    );
    if (metadataKey && !metadataEntry) return false;
    if (metadataValue) {
      const matchingEntries = Object.entries(item.metadata).filter(
        ([key]) => !metadataKey || key.toLocaleLowerCase() === metadataKey,
      );
      if (!matchingEntries.some(([, value]) => value.toLocaleLowerCase().includes(metadataValue))) {
        return false;
      }
    }
    return true;
  });
}
