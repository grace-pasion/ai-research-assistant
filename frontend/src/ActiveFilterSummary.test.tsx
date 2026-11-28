import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ActiveFilterSummary } from "./ActiveFilterSummary";

describe("active filter summary", () => {
  it("shows each active filter and stays hidden when none are applied", () => {
    const markup = renderToStaticMarkup(
      <ActiveFilterSummary filters={["Search: methods", "Source: Papers"]} />,
    );

    expect(markup).toContain("Active filters");
    expect(markup).toContain("Search: methods");
    expect(markup).toContain("Source: Papers");
    expect(renderToStaticMarkup(<ActiveFilterSummary filters={[]} />)).toBe("");
  });
});
