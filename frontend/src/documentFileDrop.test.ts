import { describe, expect, it } from "vitest";
import {
  getDroppedFiles,
  getUploadFileType,
  hasFileDragType,
} from "./documentFileDrop";

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

  it("shows a recognizable type from the file extension or MIME type", () => {
    expect(getUploadFileType(new File(["pdf"], "PAPER.PDF"))).toBe("PDF");
    expect(getUploadFileType(new File(["doc"], "notes.docx"))).toBe("Word document (DOCX)");
    expect(getUploadFileType(new File(["data"], "table.csv", { type: "text/csv" })))
      .toBe("text/csv");
    expect(getUploadFileType(new File(["data"], "unknown"))).toBe("Unknown");
  });
});
