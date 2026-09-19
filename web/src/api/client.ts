import { useCallback, useEffect, useRef, useState } from 'react';
export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
  ) {
    super(message);
  }
}
export class ApiClient {
  constructor(public baseUrl = '/api') {}
  async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...options,
        headers: {
          ...(options.body && !(options.body instanceof FormData)
            ? { 'Content-Type': 'application/json' }
            : {}),
          ...options.headers,
        },
      });
    } catch (e) {
      if (e instanceof Error && e.name === 'AbortError') throw e;
      throw new ApiError(
        'Yerel servise ulaşılamıyor. Belgü servisinin çalıştığını kontrol edip yeniden deneyin.',
        'connection',
        0,
      );
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(
        body.error?.message || `İstek tamamlanamadı (${response.status}).`,
        body.error?.code || 'request',
        response.status,
      );
    }
    return response.json() as Promise<T>;
  }
  get<T>(path: string, signal?: AbortSignal) {
    return this.request<T>(path, { signal });
  }
  post<T>(path: string, body: unknown = {}) {
    return this.request<T>(path, { method: 'POST', body: JSON.stringify(body) });
  }
  patch<T>(path: string, body: unknown) {
    return this.request<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
  }
}
export const api = new ApiClient();
export function query(values: Record<string, string | number | null | undefined>) {
  const p = new URLSearchParams();
  Object.entries(values).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') p.set(k, String(v));
  });
  return p.toString();
}
export function useResource<T>(path: string | null, refreshKey = 0) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(true),
    [version, setVersion] = useState(0);
  const previousPath = useRef<string | null>(null);
  const reload = useCallback(() => setVersion((v) => v + 1), []);
  useEffect(() => {
    if (!path) {
      setData(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    if (previousPath.current !== path) {
      setLoading(true);
      setData(null);
    }
    previousPath.current = path;
    setError('');
    api
      .get<T>(path, controller.signal)
      .then(setData)
      .catch((e) => {
        if (e.name !== 'AbortError') setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, version, refreshKey]);
  return { data, error, loading, reload };
}
export const casePath = (id: string) => `/investigations/${encodeURIComponent(id)}`;
