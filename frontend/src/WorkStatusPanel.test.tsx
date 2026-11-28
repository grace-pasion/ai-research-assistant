import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { WorkStatusPanel } from "./WorkStatusPanel";
import type { WorkStatusItem } from "./workStatus";

describe("work status error details", () => {
  it("offers copying upload and LaTeX build failures but not completed work", () => {
    const items: WorkStatusItem[] = [
      {
        id: "upload-failed",
        kind: "upload",
        title: "study.pdf",
        state: "attention",
        statusLabel: "Needs attention",
        detail: "Upload rejected by the server.",
      },
      {
        id: "latex-failed",
        kind: "latex",
        title: "Main document PDF",
        state: "attention",
        statusLabel: "Failed",
        detail: "Missing \\end{document}.",
      },
      {
        id: "latex-completed",
        kind: "latex",
        title: "Earlier PDF",
        state: "complete",
        statusLabel: "Compiled",
        detail: null,
      },
    ];

    const markup = renderToStaticMarkup(
      <WorkStatusPanel items={items} projectName="Research" />,
    );

    expect(markup.match(/Copy error details/g)).toHaveLength(2);
    expect(markup).toContain("Upload rejected by the server.");
    expect(markup).toContain("Missing \\end{document}.");
  });
});
