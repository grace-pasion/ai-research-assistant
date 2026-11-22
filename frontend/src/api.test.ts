import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends bearer authorization and decodes successful JSON responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([{ project_id: "project-1" }]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const projects = await api<{ project_id: string }[]>(
      "/api/projects",
      { method: "GET" },
      "smoke-test-token",
    );

    expect(projects).toEqual([{ project_id: "project-1" }]);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/projects");
    expect(options.method).toBe("GET");
    expect(new Headers(options.headers).get("Authorization")).toBe("Bearer smoke-test-token");
  });

  it("reports the API's error detail instead of a generic failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Research project not found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(api("/api/projects/missing", {}, "smoke-test-token")).rejects.toThrow(
      "Research project not found",
    );
  });
});
