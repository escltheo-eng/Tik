/**
 * Conversion des mouvements de prix en POINTS (l'unité de MT4/MT5).
 *
 * Un « point » = plus petit incrément de prix coté pour l'instrument. Les
 * valeurs ci-dessous sont les conventions courantes — AJUSTE-les si ton broker
 * cote différemment (c'est l'unique paramètre du calcul, garde-le juste) :
 *   BTC/USD       → 1 point = 1.00 $
 *   GOLD (XAU/USD) → 1 point = 0.01 $
 *
 * Sert à afficher, pour chaque signal, le mouvement « montée / baisse » en
 * points (à partir des seuils déjà définis × le prix). Pur affichage —
 * n'entre PAS dans le scoring (cf. ADR-018). Ne dépend d'aucun broker
 * particulier : c'est l'amplitude du marché en points, pas un coût.
 */

export const POINT_SIZE: Record<string, number> = {
  BTC: 1,
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
