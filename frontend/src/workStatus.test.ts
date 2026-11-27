import { describe, expect, it } from "vitest";
import { buildWorkStatusItems, type WorkStatusUpload } from "./workStatus";
import type { DocumentRecord } from "./types";

const document = (
  documentId: string,
  projectId: string,
  status: DocumentRecord["processing_status"],
): DocumentRecord => ({
  document_id: documentId,
  project_id: projectId,
  filename: `${documentId}.pdf`,
  file_type: "pdf",
  file_size: 1,
  processing_status: status,
  processing_error: null,
  tags: [],
  metadata: {},
  uploaded_at: "2026-01-01T00:00:00Z",
});

const upload = (
  key: string,
  status: WorkStatusUpload["status"],
  documentId: string | null = null,
): WorkStatusUpload => ({
  key,
  projectId: "project-1",
  filename: `${key}.pdf`,
  status,
  documentId,
  error: null,
});

describe("buildWorkStatusItems", () => {
  it("combines active work and avoids duplicating uploaded documents", () => {
    const items = buildWorkStatusItems(
      "project-1",
      [
        upload("accepted", "processing", "document-1"),
        upload("sending", "uploading"),
      ],
      [
        document("document-1", "project-1", "processing"),
        document("document-2", "project-1", "processing"),
      ],
      { status: "compiling", message: null },
    );

    expect(items.map(({ id, state }) => [id, state])).toEqual([
      ["upload-sending", "active"],
      ["upload-accepted", "active"],
      ["document-document-2", "active"],
      ["latex-project-1", "active"],
    ]);
  });

  it("surfaces actionable failures, keeps projects separate, and limits recent successes", () => {
    const items = buildWorkStatusItems(
      "project-1",
      [
        upload("old-ready", "ready"),
        upload("recent-ready-1", "ready"),
        upload("recent-ready-2", "ready"),
        upload("recent-ready-3", "ready"),
        upload("recent-ready-4", "ready"),
        upload("failed-upload", "failed"),
      ],
      [
        document("failed-document", "project-1", "failed"),
        document("key-document", "project-1", "needs_api_key"),
        document("quota-document", "project-1", "quota_exceeded"),
        document("other-project", "project-2", "processing"),
      ],
      { status: "failed", message: "LaTeX compiler exited with an error." },
    );

    expect(items.map(({ id, state, statusLabel }) => [id, state, statusLabel])).toEqual([
      ["upload-failed-upload", "attention", "Failed"],
      ["document-failed-document", "attention", "Failed"],
      ["document-key-document", "attention", "Needs API key"],
      ["document-quota-document", "attention", "Allowance reached"],
      ["latex-project-1", "attention", "Failed"],
      ["upload-recent-ready-4", "complete", "Ready"],
      ["upload-recent-ready-3", "complete", "Ready"],
      ["upload-recent-ready-2", "complete", "Ready"],
    ]);
    expect(items.some(({ id }) => id === "upload-old-ready")).toBe(false);
    expect(items.some(({ id }) => id.includes("other-project"))).toBe(false);
  });

  it("retains error details and represents completed compilations", () => {
    const items = buildWorkStatusItems(
      "project-1",
      [
        { ...upload("bad", "failed"), error: "Unsupported file format." },
        upload("ready-1", "ready"),
        upload("ready-2", "ready"),
        upload("ready-3", "ready"),
        upload("ready-4", "ready"),
      ],
      [],
      { status: "completed", message: null },
    );

    expect(items[0]).toMatchObject({
      id: "upload-bad",
      state: "attention",
      detail: "Unsupported file format.",
    });
    expect(items[1]).toMatchObject({
      id: "latex-project-1",
      state: "complete",
      statusLabel: "Compiled",
    });
    expect(items).toHaveLength(4);
  });
});
