import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceVersionComparison } from "./WorkspaceVersionComparison";

describe("workspace version comparison", () => {
  it("shows earlier and current content side by side", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceVersionComparison
        filename="main.py"
        versionNumber={2}
        createdAt="2026-01-01T00:00:00Z"
        previousContent="VALUE = 1"
        currentContent="VALUE = 2"
        onClose={vi.fn()}
      />,
    );

    expect(markup).toContain("Earlier version");
    expect(markup).toContain("Current working copy");
    expect(markup).toContain("VALUE = 1");
    expect(markup).toContain("VALUE = 2");
  });

  it("makes deleted files distinct from empty files", () => {
    const deletedFileMarkup = renderToStaticMarkup(
      <WorkspaceVersionComparison
        filename="helpers.py"
        versionNumber={1}
        createdAt="2026-01-01T00:00:00Z"
        previousContent="VALUE = 1"
        currentContent={null}
        onClose={vi.fn()}
      />,
    );

    const emptyFileMarkup = renderToStaticMarkup(
      <WorkspaceVersionComparison
        filename="helpers.py"
        versionNumber={1}
        createdAt="2026-01-01T00:00:00Z"
        previousContent="VALUE = 1"
        currentContent=""
        onClose={vi.fn()}
      />,
    );

    expect(deletedFileMarkup).toContain("This file is not in the current workspace.");
    expect(deletedFileMarkup).toContain("VALUE = 1");
    expect(emptyFileMarkup).toContain("Empty file");
    expect(emptyFileMarkup).not.toContain("This file is not in the current workspace.");
  });
});
