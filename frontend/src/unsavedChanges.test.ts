import { afterEach, describe, expect, it, vi } from "vitest";
import {
  confirmUnsavedEditorLeave,
  preventUnloadWithUnsavedChanges,
} from "./unsavedChanges";

describe("unsaved editor changes", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not prompt before leaving a saved editor", () => {
    const confirm = vi.fn();
    vi.stubGlobal("window", { confirm });

    expect(confirmUnsavedEditorLeave(false)).toBe(true);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("keeps the editor open when the user cancels", () => {
    const confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal("window", { confirm });

    expect(confirmUnsavedEditorLeave(true)).toBe(false);
    expect(confirm).toHaveBeenCalledWith(
      "You have unsaved changes in Writing & analysis. Leave anyway? Your changes may be lost.",
    );
  });

  it("allows leaving when the user confirms", () => {
    vi.stubGlobal("window", { confirm: vi.fn().mockReturnValue(true) });

    expect(confirmUnsavedEditorLeave(true)).toBe(true);
  });

  it("blocks browser unload when edits are unsaved", () => {
    const event = { preventDefault: vi.fn(), returnValue: "" };

    preventUnloadWithUnsavedChanges(event, true);

    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(event.returnValue).toBe("You have unsaved changes.");
  });

  it("does not block browser unload when the editor is saved", () => {
    const event = { preventDefault: vi.fn(), returnValue: "" };

    preventUnloadWithUnsavedChanges(event, false);

    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(event.returnValue).toBe("");
  });
});
