import { describe, expect, it } from "vitest";
import { resolveGlobalShortcut } from "./globalShortcuts";

describe("resolveGlobalShortcut", () => {
  it("opens global search with the platform modifier", () => {
    expect(resolveGlobalShortcut({ key: "k", ctrlKey: true }, false)).toEqual({ type: "search" });
    expect(resolveGlobalShortcut({ key: "K", metaKey: true }, false)).toEqual({ type: "search" });
  });

  it("maps note creation, upload, and each project section", () => {
    expect(resolveGlobalShortcut({ key: "n", ctrlKey: true, altKey: true }, false))
      .toEqual({ type: "new-note" });
    expect(resolveGlobalShortcut({ key: "u", metaKey: true, altKey: true }, false))
      .toEqual({ type: "upload" });
    expect(
      ["home", "documents", "papers", "collections", "notes", "latex", "assistant"].map(
        (_, index) => resolveGlobalShortcut(
          { key: String(index + 1), ctrlKey: true, altKey: true },
          false,
        ),
      ),
    ).toEqual([
      { type: "section", view: "home" },
      { type: "section", view: "documents" },
      { type: "section", view: "papers" },
      { type: "section", view: "collections" },
      { type: "section", view: "notes" },
      { type: "section", view: "latex" },
      { type: "section", view: "assistant" },
    ]);
  });

  it("ignores shortcuts while typing, in dialogs, or during key composition", () => {
    const noteShortcut = { key: "n", ctrlKey: true, altKey: true };
    expect(resolveGlobalShortcut(noteShortcut, true)).toBeNull();
    expect(resolveGlobalShortcut(noteShortcut, false)).toEqual({ type: "new-note" });
    expect(resolveGlobalShortcut({ ...noteShortcut, repeat: true }, false)).toBeNull();
    expect(resolveGlobalShortcut({ ...noteShortcut, isComposing: true }, false)).toBeNull();
    expect(resolveGlobalShortcut({ ...noteShortcut, defaultPrevented: true }, false)).toBeNull();
  });

  it("does not claim unrelated or incomplete key combinations", () => {
    expect(resolveGlobalShortcut({ key: "n" }, false)).toBeNull();
    expect(resolveGlobalShortcut({ key: "k", ctrlKey: true, shiftKey: true }, false)).toBeNull();
    expect(resolveGlobalShortcut({ key: "8", ctrlKey: true, altKey: true }, false)).toBeNull();
    expect(resolveGlobalShortcut({ key: "u", ctrlKey: true }, false)).toBeNull();
  });
});
