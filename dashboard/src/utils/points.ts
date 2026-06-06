/**
 * Conversion des mouvements de prix en POINTS (l'unité de MT4/MT5).
 *
 * Un « point » = plus petit incrément de prix coté pour l'instrument.
 *   BTC/USD  → 1 point = 0.01 $  (calibré sur MT5 ActivTrades : Digits 2,
 *              taille du tick 0.01 — fourni par la trader le 2026-06-06).
 *   GOLD (XAU/USD) → 1 point = 0.01 $  (convention courante XAUUSD Digits 2 ;
 *              NON confirmé sur le broker — à valider avec les specs MT5 Or).
 *
 * ⚠ Conséquence du passage BTC 1.00 → 0.01 : tous les comptages de points BTC
 * sont multipliés par 100 (un mouvement de 100 $ = 10 000 points, et non 100).
 * C'est la valeur réelle du broker, pas un bug. Affichage uniquement —
 * n'entre PAS dans le scoring (cf. ADR-018). Cf. ADR-025 (amplitude attendue).
 */

export const POINT_SIZE: Record<string, number> = {
  BTC: 0.01,
  GOLD: 0.01,
};

/** Taille d'un point pour l'instrument, ou null si inconnu (on n'affiche rien). */
export function pointSizeFor(entityId: string): number | null {
  return POINT_SIZE[entityId] ?? null;
}

/** Convertit une variation en % (appliquée à `price`) en nombre de points. */
export function pctToPoints(pct: number, price: number, pointSize: number): number {
  return ((pct / 100) * price) / pointSize;
}

/** Convertit une différence de prix (p1 − p0) en nombre de points. */
export function priceDiffToPoints(p1: number, p0: number, pointSize: number): number {
  return (p1 - p0) / pointSize;
}
