/** Caveat GOLD (Garde-fou 2-bis) — le vernis « conv 100% » ne doit jamais inviter à trader GOLD. */
import { describe, expect, it } from 'vitest';

import { directionalSourceCount, goldCaveat } from '@/src/utils/gold-caveat';

const ev = (...sources: string[]) => sources.map((source) => ({ source }));

describe('directionalSourceCount', () => {
  it('exclut les flux prix / indicateurs techniques (poids 0, ADR-018)', () => {
    expect(directionalSourceCount(ev('yahoo_finance', 'google_news_rss'))).toBe(1);
    expect(directionalSourceCount(ev('binance_klines', 'alternative_me_fng'))).toBe(1);
  });

  it("compte chaque source d'actu une seule fois (dédup)", () => {
    expect(
      directionalSourceCount(ev('google_news_rss', 'google_news_rss', 'gdelt_news')),
    ).toBe(2);
  });

  it('0 pour une evidence vide, absente ou 100 % technique', () => {
    expect(directionalSourceCount([])).toBe(0);
    expect(directionalSourceCount(null)).toBe(0);
    expect(directionalSourceCount(undefined)).toBe(0);
    expect(directionalSourceCount(ev('yahoo_finance', 'anomaly_detector'))).toBe(0);
  });
});

describe('goldCaveat', () => {
  it('null pour BTC — le caveat est spécifique à GOLD', () => {
    expect(goldCaveat({ entity_id: 'BTC', evidence: ev('google_news_rss') })).toBeNull();
  });

  it('GOLD : toujours le rappel Garde-fou 2-bis avec le hit MESURÉ', () => {
    const msg = goldCaveat({
      entity_id: 'GOLD',
      evidence: ev('yahoo_finance', 'google_news_rss', 'gdelt_news'),
    });
    expect(msg).toContain('4,8 %');
    expect(msg).toContain('ne pas trader GOLD');
    expect(msg).toContain('Garde-fou 2-bis');
    // 2 sources d'actu → pas de note « une seule source »
    expect(msg).not.toContain('une seule source');
  });

  it("GOLD dégradé (GDELT muette) : signale l'accord mono-source", () => {
    // Le cas réel des captures 2026-07-02 : « accord 95 % · 2 sources » où les
    // 2 sources = Yahoo (prix) + Google News → 1 seule source d'actu.
    const msg = goldCaveat({
      entity_id: 'GOLD',
      evidence: ev('yahoo_finance', 'google_news_rss'),
    });
    expect(msg).toContain("une seule source d'actu");
  });

  it("GOLD sans aucune source d'actu : le dit explicitement", () => {
    const msg = goldCaveat({ entity_id: 'GOLD', evidence: ev('yahoo_finance') });
    expect(msg).toContain("aucune source d'actu");
  });
});
