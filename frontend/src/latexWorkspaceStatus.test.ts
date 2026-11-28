import { describe, expect, it } from "vitest";
import { formatLastSavedAt, getWorkspaceSaveStatusLabel } from "./latexWorkspaceStatus";

describe("LaTeX workspace save timestamp", () => {
  it("distinguishes a new workspace from one that has been saved", () => {
    expect(getWorkspaceSaveStatusLabel("saved", null)).toBe("Not saved yet");
    expect(getWorkspaceSaveStatusLabel("saved", "2025-03-08T15:04:00.000Z")).toBe("Saved");
  });

  it("keeps a failed save distinct from the last successful save timestamp", () => {
    expect(getWorkspaceSaveStatusLabel("error", "2025-03-08T15:04:00.000Z")).toBe("Save failed");
  });

  it("does not show a timestamp before the first successful save", () => {
    expect(formatLastSavedAt(null)).toBeNull();
  });

  it("formats a saved timestamp in the user's local date and time format", () => {
    const updatedAt = "2025-03-08T15:04:00.000Z";
    const expected = new Intl.DateTimeFormat(undefined, {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(updatedAt));

    expect(formatLastSavedAt(updatedAt)).toBe(expected);
  });

  it("does not display an invalid timestamp", () => {
    expect(formatLastSavedAt("not-a-timestamp")).toBeNull();
  });
});
