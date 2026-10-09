export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function getCsrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match?.[1] ? decodeURIComponent(match[1]) : "";
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "include" };
  const mutating = method === "POST" || method === "PATCH" || method === "PUT" || method === "DELETE";
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json", ...(mutating ? { "X-CSRF-Token": getCsrfToken() } : {}) };
    init.body = JSON.stringify(body);
  } else if (mutating) {
    init.headers = { "X-CSRF-Token": getCsrfToken() };
  }
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};
