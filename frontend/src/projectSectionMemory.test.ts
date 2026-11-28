import { describe, expect, it } from "vitest";
import {
  parseRememberedProjectSection,
  projectSectionStorageKey,
  readRememberedProjectSection,
  rememberProjectSection,
  resolveProjectSection,
} from "./projectSectionMemory";

describe("remembered project sections", () => {
  it("accepts project sections but rejects global or invalid views", () => {
    expect(parseRememberedProjectSection("notes")).toBe("notes");
    expect(parseRememberedProjectSection("search")).toBeNull();
    expect(parseRememberedProjectSection("unknown")).toBeNull();
    expect(parseRememberedProjectSection(null)).toBeNull();
  });

  it("scopes saved sections to both the user and project", () => {
    expect(projectSectionStorageKey("user-1", "project-1"))
      .toBe("fieldnotes:last-section:user-1:project-1");
    expect(projectSectionStorageKey("user-1", "project-2"))
      .not.toBe(projectSectionStorageKey("user-2", "project-2"));
  });

  it("round-trips the section without leaking it to another user or project", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };

    rememberProjectSection(storage, "user-1", "project-1", "notes");

    expect(readRememberedProjectSection(storage, "user-1", "project-1")).toBe("notes");
    expect(readRememberedProjectSection(storage, "user-1", "project-2")).toBeNull();
    expect(readRememberedProjectSection(storage, "user-2", "project-1")).toBeNull();
  });

  it("uses explicit navigation before remembered state and defaults new projects to Overview", () => {
    expect(resolveProjectSection("notes", "papers")).toBe("papers");
    expect(resolveProjectSection("notes")).toBe("notes");
    expect(resolveProjectSection(null)).toBe("home");
  });
});
