/**
 * Caveat GOLD — rappel Garde-fou 2-bis sur toutes les surfaces signal GOLD.
 *
 * Découvert le 2026-07-02 (captures trader) : les cartes GOLD swing affichaient
 * « conv 100 % · accord 95 % · 2 sources » — un vernis de certitude maximal sur
 * l'actif dont le hit rate MESURÉ est 4,8 % (vs Always SHORT 80,7 %, backtest
 * 2026-05-18, Garde-fou 2-bis : « NE PAS trader GOLD avec Tik »). Pire : quand
 * GDELT est muette (429 fréquents), l'« accord 95 % » repose sur UNE SEULE
 * source d'actu (Google News) + le flux prix Yahoo — un « accord » d'une source
 * avec elle-même.
 *
 * Fonctions pures — testées dans __tests__/gold-caveat.test.ts.
 */

interface EvidenceLike {
  source: string;
}

interface SignalLike {
  entity_id: string;
  evidence: EvidenceLike[] | null | undefined;
}

/**
 * Sources NON directionnelles dans l'evidence : flux prix / indicateurs
 * techniques (poids 0 depuis ADR-018, informatifs) et détecteurs internes.
 * Tout le reste (news, sentiment, macro numérique) compte comme une source
 * d'actu qui pèse réellement dans le combined_bias.
 */
export const NON_DIRECTIONAL_SOURCES = new Set([
  'binance_klines',
  'binance_klines_1m',
  'yahoo_finance',
  'anomaly_detector',
]);

/** Nombre de sources d'actu (directionnelles) dans l'evidence d'un signal. */
export function directionalSourceCount(evidence: EvidenceLike[] | null | undefined): number {
  if (!evidence) return 0;
  const distinct = new Set(
    evidence
      .map((ev) => ev.source)
      .filter((s) => typeof s === 'string' && s.length > 0 && !NON_DIRECTIONAL_SOURCES.has(s)),
  );
  return distinct.size;
}

/**
 * Texte du caveat à afficher sur un signal GOLD, ou null pour les autres actifs.
 * Le chiffre 4,8 % est une MESURE (backtest 2026-05-18) — ne pas l'enjoliver.
 */
export function goldCaveat(signal: SignalLike): string | null {
  if (signal.entity_id !== 'GOLD') return null;
  const base = '⚠ GOLD : 4,8 % de hit mesuré — ne pas trader GOLD avec Tik (Garde-fou 2-bis)';
  const n = directionalSourceCount(signal.evidence);
  if (n === 0) return base + " · aucune source d'actu dans ce signal";
  if (n === 1) return base + " · accord fondé sur une seule source d'actu";
  return base;
}
