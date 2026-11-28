import type { DocumentRecord } from "./types";
import { getDocumentStatusPresentation } from "./documentStatus";

export type LatexCompileActivity = {
  status: "compiling" | "completed" | "failed";
  message: string | null;
};

export type WorkStatusUpload = {
  key: string;
  projectId: string;
  filename: string;
  status: DocumentRecord["processing_status"] | "uploading";
  documentId: string | null;
  error: string | null;
};

export type WorkStatusItem = {
  id: string;
  kind: "upload" | "document" | "latex";
  title: string;
  state: "active" | "complete" | "attention";
  statusLabel: string;
  detail: string | null;
};

type WorkStatusDocument = Pick<
  DocumentRecord,
  "document_id" | "project_id" | "filename" | "processing_status" | "processing_error" | "uploaded_at"
>;

function documentStatus(
  status: DocumentRecord["processing_status"],
  error: string | null,
  canRetry: boolean,
): Pick<WorkStatusItem, "state" | "statusLabel" | "detail"> {
  const presentation = getDocumentStatusPresentation(status, error, canRetry);
  return {
    state: presentation.state,
    statusLabel: presentation.label,
    detail: presentation.detail,
  };
}

function uploadStatus(
  upload: WorkStatusUpload,
  canRetry: boolean,
): Pick<WorkStatusItem, "state" | "statusLabel" | "detail"> {
  const presentation = getDocumentStatusPresentation(upload.status, upload.error, canRetry);
  return {
    state: presentation.state,
    statusLabel: presentation.label,
    detail: presentation.detail,
  };
}

export function buildWorkStatusItems(
  projectId: string,
  uploads: readonly WorkStatusUpload[],
  documents: readonly WorkStatusDocument[],
  latexCompile: LatexCompileActivity | null,
  canRetry = true,
): WorkStatusItem[] {
  const projectUploads = uploads
    .filter((upload) => upload.projectId === projectId)
    .slice()
    .reverse();
  const uploadedDocumentIds = new Set(
    projectUploads.flatMap((upload) => upload.documentId ? [upload.documentId] : []),
  );
  const active: WorkStatusItem[] = [];
  const attention: WorkStatusItem[] = [];
  const complete: WorkStatusItem[] = [];

  for (const upload of projectUploads) {
    const status = uploadStatus(upload, canRetry);
    const item: WorkStatusItem = {
      id: `upload-${upload.key}`,
      kind: "upload",
      title: upload.filename,
      ...status,
    };
    if (item.state === "active") active.push(item);
    else if (item.state === "attention") attention.push(item);
    else complete.push(item);
  }

  const projectDocuments = documents
    .filter((document) => document.project_id === projectId
      && document.processing_status !== "ready"
      && !uploadedDocumentIds.has(document.document_id))
    .slice()
    .sort((left, right) => Date.parse(right.uploaded_at) - Date.parse(left.uploaded_at));
  for (const document of projectDocuments) {
    const item: WorkStatusItem = {
      id: `document-${document.document_id}`,
      kind: "document",
      title: document.filename,
      ...documentStatus(document.processing_status, document.processing_error, canRetry),
    };
    if (item.state === "active") active.push(item);
    else attention.push(item);
  }

  if (latexCompile) {
    const item: WorkStatusItem = {
      id: `latex-${projectId}`,
      kind: "latex",
      title: "Main document PDF",
      state: latexCompile.status === "compiling"
        ? "active"
        : latexCompile.status === "failed" ? "attention" : "complete",
      statusLabel: latexCompile.status === "compiling"
        ? "Compiling"
        : latexCompile.status === "failed" ? "Failed" : "Compiled",
      detail: latexCompile.message,
    };
    if (item.state === "active") active.push(item);
    else if (item.state === "attention") attention.push(item);
    else complete.unshift(item);
  }

  return [...active, ...attention, ...complete.slice(0, 3)];
}
