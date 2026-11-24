import { afterEach, describe, expect, it, vi } from "vitest";
import { api, fetchFileBlob, fetchPdfObjectUrl } from "./api";

describe("API client", () => {
  afterEach(() => {
    vi.useRealTimers();
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

  it("retries a transient network failure on GET and succeeds when the API wakes", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify([{ project_id: "project-1" }]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const request = api<{ project_id: string }[]>("/api/projects", {}, "smoke-test-token");
    await vi.runAllTimersAsync();

    await expect(request).resolves.toEqual([{ project_id: "project-1" }]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reports a useful error when GET retries are exhausted", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    const request = api("/api/projects", {}, "smoke-test-token");
    const assertion = expect(request).rejects.toThrow(
      "Unable to reach the research API. Check your connection and try again.",
    );
    await vi.runAllTimersAsync();

    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("does not retry network failures for write requests", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api("/api/projects", { method: "POST", body: "{}" }, "smoke-test-token"))
      .rejects.toThrow("Failed to fetch");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("supports authenticated PDF compilation requests with a JSON body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("%PDF-test", {
        status: 200,
        headers: { "Content-Type": "application/pdf" },
      }),
    );
    const objectUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:compiled-pdf");
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchPdfObjectUrl(
      "/api/projects/project-1/latex/compile",
      { method: "POST", body: JSON.stringify({}) },
      "smoke-test-token",
    )).resolves.toBe("blob:compiled-pdf");

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/projects/project-1/latex/compile");
    expect(options.method).toBe("POST");
    expect(new Headers(options.headers).get("Content-Type")).toBe("application/json");
    expect(new Headers(options.headers).get("Authorization")).toBe("Bearer smoke-test-token");
    objectUrl.mockRestore();
  });

  it("uploads multipart outputs without setting a JSON content type", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("[]", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const form = new FormData();
    form.append("files", new Blob(["table"], { type: "text/plain" }), "table.tex");

    await api("/api/projects/project-1/python/artifacts", {
      method: "PUT",
      body: form,
    }, "smoke-test-token");

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/projects/project-1/python/artifacts");
    expect(new Headers(options.headers).get("Content-Type")).toBeNull();
    expect(new Headers(options.headers).get("Authorization")).toBe("Bearer smoke-test-token");
  });

  it("fetches authenticated output blobs", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("figure bytes", {
        status: 200,
        headers: { "Content-Type": "image/png" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const blob = await fetchFileBlob(
      "/api/projects/project-1/python/artifacts/figure.png",
      "smoke-test-token",
    );

    expect(blob.type).toBe("image/png");
    expect(await blob.text()).toBe("figure bytes");
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization"))
      .toBe("Bearer smoke-test-token");
  });
});
