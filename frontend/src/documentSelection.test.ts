import { describe, expect, it } from "vitest";
import { selectedTextWithin } from "./documentSelection";

describe("document text selection", () => {
  it("returns selected source text without changing its whitespace", () => {
    const start = { node: "start" };
    const end = { node: "end" };
    const container = {
      contains: (node: typeof start | null) => node === start || node === end,
    };

    expect(selectedTextWithin(container, {
      isCollapsed: false,
      rangeCount: 1,
      anchorNode: start,
      focusNode: end,
      toString: () => "\nSelected passage ",
    })).toBe("\nSelected passage ");
  });

  it("ignores collapsed, empty, and out-of-source selections", () => {
    const sourceNode = { node: "source" };
    const outsideNode = { node: "outside" };
    const container = { contains: (node: typeof sourceNode | null) => node === sourceNode };
    const baseSelection = {
      isCollapsed: false,
      rangeCount: 1,
      anchorNode: sourceNode,
      focusNode: sourceNode,
      toString: () => "Passage",
    };

    expect(selectedTextWithin(container, { ...baseSelection, isCollapsed: true })).toBeNull();
    expect(selectedTextWithin(container, { ...baseSelection, rangeCount: 0 })).toBeNull();
    expect(selectedTextWithin(container, { ...baseSelection, toString: () => "  " })).toBeNull();
    expect(selectedTextWithin(container, {
      ...baseSelection,
      focusNode: outsideNode,
    })).toBeNull();
    expect(selectedTextWithin(container, null)).toBeNull();
  });
});
