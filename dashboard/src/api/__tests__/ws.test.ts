/** Helpers WS purs — reconnexion (backoff), URL, masquage de la clé. */
import { describe, expect, it } from 'vitest';

import {
  INITIAL_BACKOFF_S,
  JITTER_MAX_S,
  MAX_BACKOFF_S,
  buildWsUrl,
  httpToWs,
  maskApiKeyInUrl,
  nextBackoff,
} from '@/src/api/ws';

describe('httpToWs', () => {
  it('convertit http→ws et https→wss', () => {
    expect(httpToWs('http://1.2.3.4:8200')).toBe('ws://1.2.3.4:8200');
    expect(httpToWs('https://tik.example.com')).toBe('wss://tik.example.com');
  });
});

describe('buildWsUrl', () => {
  it('construit le chemin signals avec la clé en query (compromis WS navigateur)', () => {
    const url = buildWsUrl('http://1.2.3.4:8200', { apiKey: 'tik_abc' });
    expect(url).toContain('/api/v1/ws/signals');
    expect(url).toContain('api_key=tik_abc');
    expect(url.startsWith('ws://')).toBe(true);
  });

  it('ajoute les filtres entity/horizon quand fournis', () => {
    const url = buildWsUrl('http://x:8200', {
      apiKey: 'k',
      entity: 'BTC',
      horizon: 'swing',
    });
    expect(url).toContain('entity=BTC');
    expect(url).toContain('horizon=swing');
  });
});

describe('nextBackoff', () => {
  it('double à chaque tentative (avec jitter borné)', () => {
    const b1 = nextBackoff(INITIAL_BACKOFF_S);
    expect(b1).toBeGreaterThanOrEqual(2 * INITIAL_BACKOFF_S);
    expect(b1).toBeLessThanOrEqual(2 * INITIAL_BACKOFF_S + JITTER_MAX_S);
  });

  it('est plafonné à MAX_BACKOFF_S (+ jitter)', () => {
    for (let i = 0; i < 20; i++) {
      const b = nextBackoff(MAX_BACKOFF_S);
      expect(b).toBeLessThanOrEqual(MAX_BACKOFF_S + JITTER_MAX_S);
    }
  });

  it('ne diminue jamais (pas de reconnexion en rafale)', () => {
    let cur = INITIAL_BACKOFF_S;
    for (let i = 0; i < 10; i++) {
      const next = nextBackoff(cur);
      expect(next).toBeGreaterThan(cur * 0.99);
      cur = next;
    }
  });
});

describe('maskApiKeyInUrl', () => {
  it('masque la valeur de la clé dans une URL de log', () => {
    const masked = maskApiKeyInUrl('ws://x:8200/api/v1/ws/signals?api_key=tik_SECRET123&entity=BTC');
    expect(masked).not.toContain('tik_SECRET123');
    expect(masked).toContain('entity=BTC');
  });
});
