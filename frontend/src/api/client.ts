export const apiBase = window.quant?.apiBase || import.meta.env.VITE_API_BASE || "http://127.0.0.1:8765";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || "请求失败");
  return data as T;
}

export function analyze(payload: Record<string, unknown>, signal?: AbortSignal) {
  return request<Record<string, any>>("/api/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
  });
}

export function quote(query: string, signal?: AbortSignal) {
  return request<Record<string, any>>(`/api/quote?q=${encodeURIComponent(query)}`, {
    cache: "no-store",
    signal,
  });
}

export function recommendations(payload: Record<string, unknown>) {
  return request<Record<string, any>>("/api/recommendations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function health() {
  return request<Record<string, any>>("/api/health");
}

export function marketOverview() {
  return request<Record<string, any>>("/api/market-overview");
}
