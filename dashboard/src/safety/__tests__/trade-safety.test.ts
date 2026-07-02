/** Feu de sécurité 🟢/🟠/🔴 — l'edge de NON-PERTE du cockpit. */
import { describe, expect, it } from 'vitest';

import {
  computeTradeSafety,
  consecutiveLosses,
  type SafetyTrade,
} from '@/src/safety/trade-safety';

const NOW = Date.parse('2026-07-02T12:00:00Z');

function closedTrade(resultPct: number, exitIso: string): SafetyTrade {
  return { status: 'closed', result_pct: resultPct, exit_time: exitIso };
}

function openTrade(entity: string, dir: string): SafetyTrade {
  return { status: 'open', result_pct: null, exit_time: null, entity_id: entity, direction: dir };
}

function base(over: Partial<Parameters<typeof computeTradeSafety>[0]> = {}) {
  return computeTradeSafety({
    macroBlock: null,
    trades: [],
    riskState: 'neutral',
    breaking: [],
    nowMs: NOW,
    ...over,
  });
}

describe('computeTradeSafety', () => {
  it('🟢 go / sizing 1 quand aucun frein', () => {
    const s = base();
    expect(s.level).toBe('go');
    expect(s.sizingFactor).toBe(1);
    expect(s.reasons).toHaveLength(0);
  });

  it('🔴 stop / sizing 0 dans la fenêtre ±4h d\'un event macro HIGH', () => {
    const s = base({ macroBlock: { event_name: 'FOMC' } });
    expect(s.level).toBe('stop');
    expect(s.sizingFactor).toBe(0);
    expect(s.reasons[0].text).toContain('FOMC');
  });

  it("🔴 stop après 2 pertes d'affilée (ta règle)", () => {
    const s = base({
      trades: [
        closedTrade(-1.2, '2026-07-02T11:00:00Z'),
        closedTrade(-0.8, '2026-07-02T10:00:00Z'),
      ],
    });
    expect(s.level).toBe('stop');
    expect(s.sizingFactor).toBe(0);
  });

  it('🟠 caution / sizing 0.5 après 1 seule perte', () => {
    const s = base({ trades: [closedTrade(-1.0, '2026-07-02T11:00:00Z')] });
    expect(s.level).toBe('caution');
    expect(s.sizingFactor).toBe(0.5);
  });

  it('🟠 caution en risk-off (VIX/crédit)', () => {
    expect(base({ riskState: 'risk_off' }).level).toBe('caution');
  });

  it('🟠 caution sur breaking < 2h ; ignoré au-delà', () => {
    const fresh = base({ breaking: [{ detected_at: '2026-07-02T11:30:00Z', category: 'fed' }] });
    expect(fresh.level).toBe('caution');
    const stale = base({ breaking: [{ detected_at: '2026-07-02T08:00:00Z', category: 'fed' }] });
    expect(stale.level).toBe('go');
  });

  it('🟠 caution quand ≥ 2 positions ouvertes même actif + même sens (empilement)', () => {
    const s = base({ trades: [openTrade('BTC', 'long'), openTrade('BTC', 'long')] });
    expect(s.level).toBe('caution');
    expect(s.reasons[0].text).toContain('empilée');
  });

  it('pas de fausse alerte : 2 positions de SENS OPPOSÉ ne comptent pas', () => {
    const s = base({ trades: [openTrade('BTC', 'long'), openTrade('BTC', 'short')] });
    expect(s.level).toBe('go');
  });
});

describe('consecutiveLosses', () => {
  it("s'arrête au premier gain (un gain réinitialise la série)", () => {
    const trades = [
      closedTrade(-1.0, '2026-07-02T11:00:00Z'), // perte la plus récente
      closedTrade(2.0, '2026-07-02T10:00:00Z'), // gain → coupe la série
      closedTrade(-1.0, '2026-07-02T09:00:00Z'),
    ];
    expect(consecutiveLosses(trades)).toBe(1);
  });

  it('ignore les trades ouverts', () => {
    expect(consecutiveLosses([openTrade('BTC', 'long')])).toBe(0);
  });
});
