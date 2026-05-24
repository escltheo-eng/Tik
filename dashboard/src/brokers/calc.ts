/**
 * Comparateur de coûts brokers — logique pure (pas de React, pas d'IO).
 *
 * Objectif : pour un mouvement de prix exprimé EN POINTS, comparer ce que
 * coûte réellement un trade chez chaque broker (Pepperstone, ActivTrades…)
 * une fois retranchés spread + commission + financement overnight (swap).
 *
 * Tout est exprimé en POINTS (la demande utilisatrice : « coût du spread en
 * terme de point »). Un « point » = plus petit incrément de prix coté par le
 * broker pour l'instrument. La SEULE règle pour que la comparaison soit juste :
 * garder la même définition du point entre les deux brokers.
 *
 * Ce qui départage un broker, trade par trade : spread, commission, swap.
 * Ce qui NE le départage PAS :
 *   - la fiscalité (impôt sur les gains) → identique quel que soit le broker
 *     en France, donc hors de ce calcul ;
 *   - le levier → il ne change pas le gain en points d'une position donnée,
 *     c'est une contrainte de marge/risque (exposée à part via maxLeverage).
 *
 * Miroir conceptuel de `_gain_for` / `evaluate_*` côté backend, mais ajoute la
 * dimension coûts (que le backtest assume explicitement comme non comptée).
 */

export type BrokerInstrumentCosts = {
  /** Spread typique observé (points). */
  spreadPoints: number;
  /** Commission aller-retour convertie en points (0 si compte « spread only »). */
  commissionPoints: number;
  /** Financement overnight LONG par nuit (points ; négatif = coût, positif = crédit). */
  swapPointsLongPerNight: number;
  /** Financement overnight SHORT par nuit (points ; négatif = coût, positif = crédit). */
  swapPointsShortPerNight: number;
};

export type BrokerSpec = {
  id: string;
  name: string;
  /** Levier maximal (ex. 500, 1000). Contrainte de marge — pas un gain. */
  maxLeverage: number;
  /** false tant que l'utilisatrice n'a pas confirmé les chiffres réels. */
  verified: boolean;
  /** Coûts par instrument (clé = entity_id Tik, ex. "BTC", "GOLD"). */
  perInstrument: Record<string, BrokerInstrumentCosts>;
};

export type TradeInputs = {
  instrument: string;
  direction: 'long' | 'short';
  /** Objectif favorable en points (le mouvement visé). null = on ne montre que le seuil. */
  grossFavorablePoints: number | null;
  /** Nuits de détention (pour le swap). */
  nights: number;
};

export type BrokerResult = {
  brokerId: string;
  brokerName: string;
  /** false si l'instrument n'est pas paramétré pour ce broker. */
  supported: boolean;
  verified: boolean;
  maxLeverage: number;
  spreadPoints: number;
  commissionPoints: number;
  /** Swap total = swap/nuit × nuits (signé). */
  swapPointsTotal: number;
  /** Coût d'entrée = spread + commission (payé pour ouvrir+fermer). */
  entryCostPoints: number;
  /** Mouvement favorable minimal pour ne rien perdre (= entryCost − swapTotal). */
  breakevenPoints: number;
  /** Gain net à l'objectif (= objectif − entryCost + swapTotal). null si pas d'objectif. */
  netPoints: number | null;
};

/** Calcule le résultat d'un trade pour un broker donné. */
export function computeBrokerResult(spec: BrokerSpec, trade: TradeInputs): BrokerResult {
  const inst = spec.perInstrument[trade.instrument];
  if (!inst) {
    return {
      brokerId: spec.id,
      brokerName: spec.name,
      supported: false,
      verified: spec.verified,
      maxLeverage: spec.maxLeverage,
      spreadPoints: 0,
      commissionPoints: 0,
      swapPointsTotal: 0,
      entryCostPoints: 0,
      breakevenPoints: 0,
      netPoints: null,
    };
  }

  const swapPerNight =
    trade.direction === 'short' ? inst.swapPointsShortPerNight : inst.swapPointsLongPerNight;
  const swapPointsTotal = swapPerNight * Math.max(0, trade.nights);
  const entryCostPoints = inst.spreadPoints + inst.commissionPoints;
  const breakevenPoints = entryCostPoints - swapPointsTotal;
  const netPoints =
    trade.grossFavorablePoints == null
      ? null
      : trade.grossFavorablePoints - entryCostPoints + swapPointsTotal;

  return {
    brokerId: spec.id,
    brokerName: spec.name,
    supported: true,
    verified: spec.verified,
    maxLeverage: spec.maxLeverage,
    spreadPoints: inst.spreadPoints,
    commissionPoints: inst.commissionPoints,
    swapPointsTotal,
    entryCostPoints,
    breakevenPoints,
    netPoints,
  };
}

/**
 * Compare tous les brokers pour un même trade et désigne le meilleur.
 *
 * Le classement se fait sur le seuil de rentabilité (breakevenPoints) croissant.
 * C'est équivalent à classer par gain net décroissant — net = objectif −
 * breakeven, et l'objectif est le même chez tous les brokers — mais ça marche
 * AUSSI quand aucun objectif n'est saisi. Le meilleur broker est donc celui
 * qui demande le plus petit mouvement favorable pour devenir rentable.
 */
export function compareBrokers(
  specs: BrokerSpec[],
  trade: TradeInputs,
): { results: BrokerResult[]; bestId: string | null } {
  const results = specs
    .map((s) => computeBrokerResult(s, trade))
    .filter((r) => r.supported);

  const ranked = [...results].sort((a, b) => a.breakevenPoints - b.breakevenPoints);
  const bestId = ranked.length > 0 ? ranked[0].brokerId : null;

  return { results, bestId };
}
