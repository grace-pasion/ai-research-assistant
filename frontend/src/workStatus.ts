import type { DocumentRecord } from "./types";

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
): Pick<WorkStatusItem, "state" | "statusLabel" | "detail"> {
  if (status === "processing") {
    return {
      state: "active",
      statusLabel: "Processing",
      detail: error ?? "Text extraction and indexing are in progress.",
    };
  }
  if (status === "ready") {
    return {
      state: "complete",
      statusLabel: "Ready",
      detail: error,
    };
  }
  if (status === "needs_api_key") {
    return {
      state: "attention",
      statusLabel: "Needs API key",
      detail: error ?? "Text is available; configure an API key for AI features.",
    };
  }
  if (status === "quota_exceeded") {
    return {
      state: "attention",
      statusLabel: "Allowance reached",
      detail: error ?? "Document processing reached the AI usage allowance.",
    };
  }
  return {
    state: "attention",
    statusLabel: "Failed",
    detail: error ?? "Document processing failed.",
  };
}

function uploadStatus(
  upload: WorkStatusUpload,
): Pick<WorkStatusItem, "state" | "statusLabel" | "detail"> {
  if (upload.status === "uploading") {
    return {
      state: "active",
      statusLabel: "Uploading",
      detail: "Sending this file to the project.",
    };
  }
  return documentStatus(upload.status, upload.error);
}

export function buildWorkStatusItems(
  projectId: string,
  uploads: readonly WorkStatusUpload[],
  documents: readonly WorkStatusDocument[],
  latexCompile: LatexCompileActivity | null,
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
    const status = uploadStatus(upload);
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
      ...documentStatus(document.processing_status, document.processing_error),
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
