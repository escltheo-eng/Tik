/**
 * Client HTTP partagé du dashboard.
 *
 * Wrapper minimaliste de `fetch` : préfixe `/api/v1`, Bearer token
 * automatique, timeout configurable, mapping HTTP → exceptions typées.
 *
 * Miroir simplifié de `sdk/_http.py` côté Python. Les couches optionnelles
 * (cache local, circuit breaker) viendront plus tard si besoin.
 *
 * ADR-003 : ce client expose `get` et `post` génériques mais le dashboard
 * n'appellera jamais d'endpoint d'exécution d'ordre — il n'y en a pas
 * côté core de toute façon.
 */

import {
  AuthError,
  NetworkError,
  NotFoundError,
  ServerError,
  TikError,
} from './errors';

export const USER_AGENT = 'tik-dashboard/0.5.0';
export const API_PREFIX = '/api/v1';
const DEFAULT_TIMEOUT_MS = 10_000;

export type QueryValue = string | number | boolean | undefined | null;
export type QueryParams = Record<string, QueryValue>;

export interface HttpClientOptions {
  baseUrl: string;
  apiKey: string | null;
  timeoutMs?: number;
}

export class HttpClient {
  readonly baseUrl: string;
  readonly apiKey: string | null;
  readonly timeoutMs: number;

  constructor({ baseUrl, apiKey, timeoutMs = DEFAULT_TIMEOUT_MS }: HttpClientOptions) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.apiKey = apiKey;
    this.timeoutMs = timeoutMs;
  }

  async get<T>(
    path: string,
    params?: QueryParams,
    opts?: { authenticated?: boolean },
  ): Promise<T> {
    const authenticated = opts?.authenticated ?? true;
    const url = this._buildUrl(path, params);
    const headers = this._buildHeaders(authenticated);

    const response = await this._fetchWithTimeout(url, { method: 'GET', headers });
    return this._parse<T>(response);
  }

  async post<T>(
    path: string,
    body: unknown,
    opts?: { authenticated?: boolean; expectedStatus?: number[] },
  ): Promise<T> {
    const authenticated = opts?.authenticated ?? true;
    const expectedStatus = opts?.expectedStatus ?? [200, 201];
    const url = this._buildUrl(path);
    const headers = {
      ...this._buildHeaders(authenticated),
      'Content-Type': 'application/json',
    };

    const response = await this._fetchWithTimeout(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });
    return this._parse<T>(response, expectedStatus);
  }

  async patch<T>(
    path: string,
    body: unknown,
    opts?: { authenticated?: boolean; expectedStatus?: number[] },
  ): Promise<T> {
    const authenticated = opts?.authenticated ?? true;
    const expectedStatus = opts?.expectedStatus ?? [200];
    const url = this._buildUrl(path);
    const headers = {
      ...this._buildHeaders(authenticated),
      'Content-Type': 'application/json',
    };

    const response = await this._fetchWithTimeout(url, {
      method: 'PATCH',
      headers,
      body: JSON.stringify(body),
    });
    return this._parse<T>(response, expectedStatus);
  }

  async del<T>(
    path: string,
    opts?: { authenticated?: boolean; expectedStatus?: number[] },
  ): Promise<T> {
    const authenticated = opts?.authenticated ?? true;
    const expectedStatus = opts?.expectedStatus ?? [200, 204];
    const url = this._buildUrl(path);
    const headers = this._buildHeaders(authenticated);

    const response = await this._fetchWithTimeout(url, { method: 'DELETE', headers });
    return this._parse<T>(response, expectedStatus);
  }

  private _buildUrl(path: string, params?: QueryParams): string {
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    const url = new URL(`${this.baseUrl}${API_PREFIX}${cleanPath}`);
    if (params) {
      for (const [key, val] of Object.entries(params)) {
        if (val === undefined || val === null) continue;
        url.searchParams.append(key, String(val));
      }
    }
    return url.toString();
  }

  private _buildHeaders(authenticated: boolean): Record<string, string> {
    const headers: Record<string, string> = {
      'User-Agent': USER_AGENT,
      Accept: 'application/json',
    };
    if (authenticated && this.apiKey) {
      headers.Authorization = `Bearer ${this.apiKey}`;
    }
    return headers;
  }

  private async _fetchWithTimeout(url: string, init: RequestInit): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      return await fetch(url, { ...init, signal: controller.signal });
    } catch (err) {
      const e = err as Error;
      if (e.name === 'AbortError') {
        throw new NetworkError(`timeout (${this.timeoutMs}ms) on ${url}`);
      }
      throw new NetworkError(`network error on ${url}: ${e.message}`);
    } finally {
      clearTimeout(timer);
    }
  }

  private async _parse<T>(response: Response, expectedStatus: number[] = [200]): Promise<T> {
    const status = response.status;
    if (expectedStatus.includes(status)) {
      const text = await response.text();
      if (!text) return null as T;
      try {
        return JSON.parse(text) as T;
      } catch {
        throw new TikError(`invalid JSON in response: ${text.slice(0, 200)}`);
      }
    }
    const bodyExcerpt = (await response.text()).slice(0, 200);
    if (status === 401 || status === 403) {
      throw new AuthError(`${status} ${response.statusText}: ${bodyExcerpt}`);
    }
    if (status === 404) {
      throw new NotFoundError(`404 not found: ${bodyExcerpt}`);
    }
    if (status >= 500 && status < 600) {
      throw new ServerError(`${status} ${response.statusText}: ${bodyExcerpt}`);
    }
    throw new TikError(`unexpected HTTP ${status}: ${bodyExcerpt}`);
  }
}
