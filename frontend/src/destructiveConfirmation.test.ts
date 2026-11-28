import { afterEach, describe, expect, it, vi } from "vitest";
import { confirmDestructiveAction } from "./destructiveConfirmation";

describe("destructive action confirmations", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("names the target and explains the consequence before proceeding", () => {
    const confirm = vi.fn().mockReturnValue(true);
    vi.stubGlobal("window", { confirm });

    expect(confirmDestructiveAction(
      "Delete",
      "analysis.pdf",
      "This also deletes its extracted text from the project.",
    )).toBe(true);
    expect(confirm).toHaveBeenCalledWith(
      "Delete “analysis.pdf”? This also deletes its extracted text from the project.",
    );
  });

  it("does not proceed when the user cancels", () => {
    const confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal("window", { confirm });

    expect(confirmDestructiveAction("Remove", "Paper title", "This only removes it from this project."))
      .toBe(false);
  });
});
