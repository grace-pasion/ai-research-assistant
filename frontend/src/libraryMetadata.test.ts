import { describe, expect, it } from "vitest";
import {
  filterByLibraryMetadata,
  hasLibraryMetadataFilters,
  libraryMetadataFilterLabels,
  type LibraryMetadataFields,
} from "./libraryMetadata";

type LibraryItem = LibraryMetadataFields & { title: string };

describe("library metadata filters", () => {
  const items: LibraryItem[] = [
    { title: "Tagged document", tags: ["Clinical", "Review"], metadata: { Region: "North America" } },
    { title: "Tagged paper", tags: ["clinical"], metadata: { design: "Randomized trial" } },
    { title: "Unlabeled item", tags: [], metadata: {} },
  ];

  it("matches tags without case sensitivity and requires an exact tag", () => {
    expect(filterByLibraryMetadata(items, { tag: "CLINICAL", metadataKey: "", metadataValue: "" })
      .map((item) => item.title)).toEqual(["Tagged document", "Tagged paper"]);
    expect(filterByLibraryMetadata(items, { tag: "clinic", metadataKey: "", metadataValue: "" }))
      .toEqual([]);
  });

  it("filters metadata by optional key and a case-insensitive partial value", () => {
    expect(filterByLibraryMetadata(items, {
      tag: "",
      metadataKey: "region",
      metadataValue: "north",
    }).map((item) => item.title)).toEqual(["Tagged document"]);
    expect(filterByLibraryMetadata(items, {
      tag: "",
      metadataKey: "",
      metadataValue: "trial",
    }).map((item) => item.title)).toEqual(["Tagged paper"]);
  });

  it("does not match values under a different requested metadata key", () => {
    expect(filterByLibraryMetadata(items, {
      tag: "",
      metadataKey: "region",
      metadataValue: "randomized",
    })).toEqual([]);
  });

  it("only treats non-whitespace metadata values as active filters", () => {
    expect(hasLibraryMetadataFilters({ tag: "", metadataKey: "", metadataValue: "" })).toBe(false);
    expect(hasLibraryMetadataFilters({ tag: "  ", metadataKey: "", metadataValue: "" })).toBe(false);
    expect(hasLibraryMetadataFilters({ tag: "", metadataKey: "study", metadataValue: "" })).toBe(true);
    expect(hasLibraryMetadataFilters({ tag: "", metadataKey: "", metadataValue: "randomized" })).toBe(true);
  });

  it("labels only the metadata filters that are active", () => {
    expect(libraryMetadataFilterLabels({
      tag: "  clinical ",
      metadataKey: "  design ",
      metadataValue: "  randomized  ",
    })).toEqual([
      "Tag: clinical",
      "Metadata field: design",
      "Metadata value: randomized",
    ]);
    expect(libraryMetadataFilterLabels({ tag: " ", metadataKey: "", metadataValue: "" })).toEqual([]);
  });
});
