import { describe, expect, it } from "vitest";
import { fetchProjectData } from "./projectData";

describe("project data loading", () => {
  it("ignores an older project's response when it finishes last", async () => {
    let selectedProjectId = "project-old";
    const pending = new Map<string, (value: unknown) => void>();
    const request = <T,>(path: string) =>
      new Promise<T>((resolve) => {
        pending.set(path, (value) => resolve(value as T));
      });
    const applied: string[] = [];

    const oldRequest = fetchProjectData(
      "project-old",
      request,
      () => selectedProjectId === "project-old",
      () => applied.push("project-old"),
    );
    selectedProjectId = "project-current";
    const currentRequest = fetchProjectData(
      "project-current",
      request,
      () => selectedProjectId === "project-current",
      () => applied.push("project-current"),
    );

    const resolveProject = (projectId: string) => {
      for (const resource of ["documents", "papers", "assistant/conversations"]) {
        pending.get(`/api/projects/${projectId}/${resource}`)?.([]);
      }
    };
    resolveProject("project-current");
    await currentRequest;
    resolveProject("project-old");
    await oldRequest;

    expect(applied).toEqual(["project-current"]);
  });
});
