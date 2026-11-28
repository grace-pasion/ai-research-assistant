import { describe, expect, it } from "vitest";
import { getDroppedFiles, hasFileDragType } from "./documentFileDrop";

describe("document file drops", () => {
  it("recognizes file drags without treating other drags as uploads", () => {
    expect(hasFileDragType(["Files"])).toBe(true);
    expect(hasFileDragType(["text/plain"])).toBe(false);
    expect(hasFileDragType([])).toBe(false);
  });

  it("preserves every dropped file for the existing bulk upload flow", () => {
    const files = [
      new File(["first"], "first.pdf"),
      new File(["second"], "second.docx"),
    ];

    expect(getDroppedFiles({ files })).toEqual(files);
  });
});
