import { describe, expect, it } from "vitest";
import { allAssistantSources, withoutAssistantSource } from "./assistantSources";
import type { DocumentRecord, Paper } from "./types";

const document = (
  document_id: string,
  processing_status: DocumentRecord["processing_status"],
): DocumentRecord => ({
  document_id,
  project_id: "project-1",
  filename: `${document_id}.pdf`,
  file_type: "pdf",
  file_size: 1,
  processing_status,
  processing_error: null,
  tags: [],
  metadata: {},
  uploaded_at: "2026-01-01T00:00:00Z",
});

const paper = (paper_id: string): Paper => ({
  paper_id,
  external_paper_id: paper_id,
  api_provider: "openalex",
  title: paper_id,
  abstract: null,
  publication_year: null,
  doi: null,
  paper_url: null,
  venue: null,
  citation_count: null,
  authors: [],
  saved: true,
  screening_status: "unread",
  screening_note: "",
  tags: [],
  metadata: {},
});

describe("assistant source selection", () => {
  it("selects only ready documents and all saved project papers", () => {
    expect(allAssistantSources(
      [document("ready", "ready"), document("processing", "processing")],
      [paper("paper-1")],
    )).toEqual({
      document_ids: ["ready"],
      paper_ids: ["paper-1"],
    });
  });

  it("excludes only the source selected for revision", () => {
    const selection = { document_ids: ["doc-1", "doc-2"], paper_ids: ["paper-1"] };

    expect(withoutAssistantSource(selection, {
      kind: "document",
      source_id: "chunk-1",
      title: "doc-1.pdf",
      excerpt: "Passage",
      document_id: "doc-1",
      page_number: 4,
      paper_id: null,
      paper_url: null,
    })).toEqual({ document_ids: ["doc-2"], paper_ids: ["paper-1"] });
    expect(selection.document_ids).toEqual(["doc-1", "doc-2"]);
  });
});
