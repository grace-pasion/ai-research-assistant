import { describe, expect, it } from "vitest";
import { preparePaperAbstract } from "./paperAbstract";

describe("paper abstract previews", () => {
  it("keeps short abstracts intact and handles missing abstracts", () => {
    expect(preparePaperAbstract(null)).toEqual({
      text: "",
      preview: "",
      hasMore: false,
    });
    expect(preparePaperAbstract("A short abstract.")).toEqual({
      text: "A short abstract.",
      preview: "A short abstract.",
      hasMore: false,
    });
  });

  it("only offers expansion when the cleaned abstract exceeds the limit", () => {
    expect(preparePaperAbstract("a".repeat(500)).hasMore).toBe(false);
    const longAbstract = preparePaperAbstract("a".repeat(501));

    expect(longAbstract.hasMore).toBe(true);
    expect(longAbstract.preview).toBe("a".repeat(500));
    expect(longAbstract.text).toBe("a".repeat(501));
  });

  it("keeps block markup from concatenating words and does not split Unicode characters", () => {
    const markup = `<p>${"a".repeat(499)}😀</p><p>Final word</p>`;
    const abstract = preparePaperAbstract(markup);

    expect(abstract.preview).toBe(`${"a".repeat(499)}😀`);
    expect(abstract.text).toBe(`${"a".repeat(499)}😀 Final word`);
    expect(abstract.hasMore).toBe(true);
  });
});
