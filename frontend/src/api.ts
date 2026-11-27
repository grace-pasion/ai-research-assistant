const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const ADMIN_TOKEN_KEY = "fieldnotes_admin_token";
const GET_RETRY_DELAYS_MS = [1_000, 3_000, 7_000] as const;

async function fetchWithNetworkRetry(url: string, options: RequestInit): Promise<Response> {
  const canRetry = (options.method ?? "GET").toUpperCase() === "GET";

  for (let attempt = 0; ; attempt += 1) {
    try {
      return await fetch(url, options);
    } catch (error) {
      if (!(error instanceof TypeError) || !canRetry || options.signal?.aborted) throw error;
      const delay = GET_RETRY_DELAYS_MS[attempt];
      if (delay === undefined) {
        throw new Error("Unable to reach the research API. Check your connection and try again.");
      }
      await new Promise<void>((resolve) => setTimeout(resolve, delay));
    }
  }
}

export function getToken(): string | null {
  return localStorage.getItem("research_assistant_token");
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem("research_assistant_token", token);
  else localStorage.removeItem("research_assistant_token");
}

export function getAdminToken(): string | null {
  return localStorage.getItem(ADMIN_TOKEN_KEY);
}

export function setAdminToken(token: string | null): void {
  if (token) localStorage.setItem(ADMIN_TOKEN_KEY, token);
  else localStorage.removeItem(ADMIN_TOKEN_KEY);
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
  token = getToken(),
): Promise<T> {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetchWithNetworkRetry(`${API_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      message = body.detail ?? message;
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}

export async function downloadFile(
  path: string,
  filename: string,
  options: RequestInit = {},
): Promise<void> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetchWithNetworkRetry(`${API_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    let message = `Download failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      message = body.detail ?? message;
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}

export async function fetchPdfObjectUrl(
  path: string,
  options: RequestInit = {},
  token = getToken(),
): Promise<string> {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetchWithNetworkRetry(`${API_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    let message = `Could not load PDF (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      message = body.detail ?? message;
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }
  const content = await response.blob();
  return URL.createObjectURL(new Blob([content], { type: "application/pdf" }));
}

export async function fetchFileBlob(
  path: string,
  token = getToken(),
): Promise<Blob> {
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetchWithNetworkRetry(`${API_URL}${path}`, { headers });
  if (!response.ok) {
    let message = `Could not load file (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      message = body.detail ?? message;
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }
  return response.blob();
}
