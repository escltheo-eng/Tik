/**
 * Helpers WebSocket — purs et trivialement testables.
 *
 * Miroir de `sdk/_ws.py` côté Python. La boucle de connexion vit dans
 * `stream.ts` ; ces fonctions ne font que de la conversion d'URL et du
 * calcul de backoff.
 */

const WS_PATH = '/api/v1/ws/signals';

export const INITIAL_BACKOFF_S = 1.0;
export const MAX_BACKOFF_S = 60.0;
export const JITTER_MAX_S = 0.5;

export function httpToWs(url: string): string {
  if (url.startsWith('https://')) return 'wss://' + url.slice('https://'.length);
  if (url.startsWith('http://')) return 'ws://' + url.slice('http://'.length);
  if (url.startsWith('ws://') || url.startsWith('wss://')) return url;
  throw new Error(`unsupported URL scheme: ${url}`);
}

export interface BuildWsUrlOptions {
  apiKey: string;
  entity?: string;
  horizon?: string;
}

export function buildWsUrl(baseUrl: string, opts: BuildWsUrlOptions): string {
  const wsBase = httpToWs(baseUrl.replace(/\/+$/, ''));
  const params = new URLSearchParams();
  params.set('api_key', opts.apiKey);
  if (opts.entity) params.set('entity', opts.entity);
  if (opts.horizon) params.set('horizon', opts.horizon);
  return `${wsBase}${WS_PATH}?${params.toString()}`;
}

/**
 * Doublage exponentiel plafonné, plus jitter [0, JITTER_MAX_S] pour
 * éviter le thundering herd quand plusieurs clients reconnectent
 * simultanément après un crash du core.
 */
export function nextBackoff(current: number): number {
  const next = Math.min(current * 2, MAX_BACKOFF_S);
  return next + Math.random() * JITTER_MAX_S;
}

/**
 * Masque l'api_key dans une URL WS (pour les logs).
 */
export function maskApiKeyInUrl(url: string): string {
  return url.replace(/api_key=[^&]+/, 'api_key=***');
}
