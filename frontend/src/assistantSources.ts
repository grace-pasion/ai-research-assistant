import type { DocumentRecord, Paper, Source } from "./types";

export type AssistantSourceSelection = {
  document_ids: string[];
  paper_ids: string[];
};

export function allAssistantSources(documents: DocumentRecord[], papers: Paper[]): AssistantSourceSelection {
  return {
    document_ids: documents.filter((document) => document.processing_status === "ready").map((document) => document.document_id),
    paper_ids: papers.map((paper) => paper.paper_id),
  };
}

export function withoutAssistantSource(selection: AssistantSourceSelection, source: Source): AssistantSourceSelection {
  return {
    document_ids: selection.document_ids.filter((id) => id !== source.document_id),
    paper_ids: selection.paper_ids.filter((id) => id !== source.paper_id),
  };
}
