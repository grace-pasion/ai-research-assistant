import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { CrossProjectSearch } from "./CrossProjectSearch";
import type { Project } from "./types";

describe("cross-project search query", () => {
  it("renders the query supplied by its parent so navigation can remount the view", () => {
    const request = async <T,>(_path: string): Promise<T> => {
      throw new Error("Search history should not load during server rendering.");
    };
    const projects: Project[] = [];

    const markup = renderToStaticMarkup(
      <CrossProjectSearch
        projects={projects}
        query="randomized trial"
        onQueryChange={vi.fn()}
        request={request}
        onOpen={vi.fn()}
      />,
    );

    expect(markup).toContain('value="randomized trial"');
  });
});
