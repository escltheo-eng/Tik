/** Règles d'alerte partagées WS/resync — source unique de vérité (D-2). */
import { describe, expect, it } from 'vitest';

import type { Signal } from '@/src/api/types';
import { deriveAlertTypes } from '@/src/alerts/derive';

const THRESHOLD = 0.5;

function signal(over: Partial<Signal> = {}): Signal {
  return {
    id: 'TIK-TEST',
    timestamp: '2026-07-02T10:00:00Z',
    entity_id: 'BTC',
    horizon: 'swing',
    direction: 'neutral',
    confidence: 0.3,
    veracity: 0.85,
    hypothesis: null,
    counter_scenarios: [],
    evidence: [],
    triggers: [],
    sources_count: 2,
    expiry: '2026-07-09T10:00:00Z',
    advisory: {},
    circuit_breaker_status: 'ok',
    ...over,
  } as Signal;
}

describe('deriveAlertTypes', () => {
  it('signal sain → aucune alerte', () => {
    expect(deriveAlertTypes(signal(), THRESHOLD)).toEqual([]);
  });

  it('crash_warning sur advisory.macro_crash_warning', () => {
    const s = signal({ advisory: { macro_crash_warning: true } as Signal['advisory'] });
    expect(deriveAlertTypes(s, THRESHOLD)).toContain('crash_warning');
  });

  it('fake_news_detected sur circuit breaker ≠ ok', () => {
    const s = signal({ circuit_breaker_status: 'degraded' });
    expect(deriveAlertTypes(s, THRESHOLD)).toContain('fake_news_detected');
  });

  it('veracity_collapse sous le seuil', () => {
    const s = signal({ veracity: 0.4 });
    expect(deriveAlertTypes(s, THRESHOLD)).toContain('veracity_collapse');
  });

  it('micro shadow : JAMAIS fake_news ni collapse (degraded + 0.70 by-design)', () => {
    const s = signal({ horizon: 'micro', circuit_breaker_status: 'degraded', veracity: 0.4 });
    expect(deriveAlertTypes(s, THRESHOLD)).toEqual([]);
  });

  it('micro shadow : le crash_warning macro passe quand même', () => {
    const s = signal({
      horizon: 'micro',
      circuit_breaker_status: 'degraded',
      advisory: { macro_crash_warning: true } as Signal['advisory'],
    });
    expect(deriveAlertTypes(s, THRESHOLD)).toEqual(['crash_warning']);
  });

  it('cumul possible : degraded + veracity basse → 2 alertes', () => {
    const s = signal({ circuit_breaker_status: 'degraded', veracity: 0.3 });
    expect(deriveAlertTypes(s, THRESHOLD)).toHaveLength(2);
  });
});
