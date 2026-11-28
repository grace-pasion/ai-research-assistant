import { describe, expect, it } from "vitest";
import { getDocumentStatusPresentation } from "./documentStatus";

describe("getDocumentStatusPresentation", () => {
  it.each([
    ["uploading", "Uploading", "active"],
    ["processing", "Extracting", "active"],
    ["ready", "Ready", "complete"],
    ["needs_api_key", "Needs attention", "attention"],
    ["quota_exceeded", "Needs attention", "attention"],
    ["failed", "Needs attention", "attention"],
  ] as const)("labels %s as %s", (status, label, state) => {
    expect(getDocumentStatusPresentation(status)).toMatchObject({ label, state });
  });

  it("explains how to retry a processing failure and preserves its error", () => {
    const status = getDocumentStatusPresentation("failed", "The file could not be read.");

    expect(status.detail).toContain("The file could not be read.");
    expect(status.detail).toContain("Select Retry or Reprocess");
    expect(status.detail).toContain("non-password-protected");
  });

  it("clarifies which text features remain available without an API key", () => {
    expect(getDocumentStatusPresentation("needs_api_key").detail).toContain(
      "Text is available to read and search. Configure OPENAI_API_KEY",
    );
  });

  it("directs collaborators without retry access to a project editor", () => {
    expect(getDocumentStatusPresentation("failed", "Embedding failed.", false).detail).toContain(
      "Ask a project editor to retry or reprocess it.",
    );
  });
});
