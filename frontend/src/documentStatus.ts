import type { DocumentRecord } from "./types";

export type DocumentStatus = DocumentRecord["processing_status"] | "uploading";

export type DocumentStatusPresentation = {
  state: "active" | "complete" | "attention";
  label: string;
  detail: string;
};

export function getDocumentStatusPresentation(
  status: DocumentStatus,
  error: string | null = null,
  canRetry = true,
): DocumentStatusPresentation {
  if (status === "uploading") {
    return {
      state: "active",
      label: "Uploading",
      detail: "Sending this file to the project.",
    };
  }
  if (status === "processing") {
    return {
      state: "active",
      label: "Extracting",
      detail: "Extracting text and preparing the document.",
    };
  }
  if (status === "ready") {
    return {
      state: "complete",
      label: "Ready",
      detail: "Extracted text is ready to read and search.",
    };
  }
  if (status === "needs_api_key") {
    return {
      state: "attention",
      label: "Needs attention",
      detail: error
        ? canRetry
          ? error
          : `${error} Contact the project administrator to configure the API key.`
        : canRetry
          ? "Text is available to read and search. Configure OPENAI_API_KEY, then select Reprocess to enable semantic search."
          : "Text is available to read and search. Ask the project administrator to configure OPENAI_API_KEY for semantic search.",
    };
  }
  if (status === "quota_exceeded") {
    return {
      state: "attention",
      label: "Needs attention",
      detail: [
        error ?? "Text is retained. Retry after the daily AI allowance resets, or split the file if it exceeds the limit.",
        canRetry ? null : "A project editor can retry it after the allowance resets.",
      ].filter(Boolean).join(" "),
    };
  }
  return {
    state: "attention",
    label: "Needs attention",
    detail: [
      error ?? "Document processing failed.",
      canRetry
        ? "Select Retry or Reprocess to try again. If it fails again, delete it and upload a readable, supported, non-password-protected copy."
        : "Ask a project editor to retry or reprocess it. If it fails again, have them upload a readable, supported, non-password-protected copy.",
    ].join(" "),
  };
}
