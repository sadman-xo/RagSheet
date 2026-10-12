export class ApiError extends Error {
  status: number;
  code: string;
  detail: Record<string, unknown>;
  retryAfter?: number;

  constructor(status: number, code: string, message: string, detail: Record<string, unknown> = {}, retryAfter?: number) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.retryAfter = retryAfter;
  }
}

export const UNAUTHORIZED_EVENT = "panorama:unauthorized";

async function parseError(res: Response): Promise<ApiError> {
  let code = "HTTP_" + res.status;
  let message = res.statusText || "Request failed";
  let detail: Record<string, unknown> = {};
  try {
    const body = await res.json();
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      detail = body.error.detail ?? {};
    }
  } catch {
    /* not JSON */
  }
  const ra = res.headers.get("Retry-After");
  return new ApiError(res.status, code, message, detail, ra ? Number(ra) : undefined);
}

export async function api<T>(path: string, opts: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined ? "POST" : "GET");
  const res = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    headers: opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });
  if (!res.ok) {
    const err = await parseError(res);
    if (res.status === 401 && !path.startsWith("/auth/login")) {
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    }
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const get = <T>(path: string, signal?: AbortSignal) => api<T>(path, { signal });
export const post = <T>(path: string, body: unknown, signal?: AbortSignal) => api<T>(path, { method: "POST", body, signal });
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body });

/** POST that returns a file (CSV export). */
export async function downloadPost(path: string, body: unknown, fallbackName: string): Promise<void> {
  const res = await fetch("/api" + path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await parseError(res);
  await saveResponse(res, fallbackName);
}

export async function downloadGet(path: string, fallbackName: string): Promise<void> {
  const res = await fetch("/api" + path, { credentials: "same-origin" });
  if (!res.ok) throw await parseError(res);
  await saveResponse(res, fallbackName);
}

async function saveResponse(res: Response, fallbackName: string) {
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") ?? "";
  const m = /filename="([^"]+)"/.exec(cd);
  saveBlob(blob, m ? m[1] : fallbackName);
}

export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "OUT_OF_SCOPE") return "This filter contains values outside your data scope.";
    return e.message;
  }
  if (e instanceof Error) return e.message;
  return "Something went wrong.";
}
