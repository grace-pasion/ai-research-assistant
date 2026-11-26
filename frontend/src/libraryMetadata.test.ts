import { describe, expect, it } from "vitest";
import { filterByLibraryMetadata, type LibraryMetadataFields } from "./libraryMetadata";

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
});
