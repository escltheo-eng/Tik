/**
 * relations.ts — modèle PUR de la vue « relations » (deux soleils) de l'observatoire.
 *
 * Montre BTC et GOLD ENSEMBLE et met en évidence un fait STRUCTUREL réel : quelles
 * sources OSINT sont propres à un actif, et quelle(s) source(s) alimentent les DEUX
 * (le « pont »). Aujourd'hui une seule source est partagée : Google News.
 *
 * Honnêteté (Axe #1 / ADR-004) : comme la vue orbitale, AUCUN « poids d'influence »
 * inventé (la veracity est une moyenne NON pondérée → aucune source ne pèse plus
 * qu'une autre). On ne montre que des faits : sens + accord de chaque actif, état de
 * chaque source, et le texte réel qu'elle a produit.
 *
 * Construit PAR-DESSUS buildOrbitalModel (même source de vérité : source_health +
 * dernier signal swing) → pur, mêmes entrées = même sortie, testable par exécution.
 */

import type { Signal, SourceHealth } from '@/src/api/types';
import { buildOrbitalModel, type OrbitalModel, type OrbitalSource } from './orbital';

/**
 * Une source partagée par les deux actifs : la MÊME source, vue côté BTC et côté
 * GOLD. Les deux faces peuvent différer (santé propre — `google_news_btc` vs
 * `google_news_gold` — et texte propre selon le signal de chaque actif).
 */
export interface SharedRelation {
  label: string;
  btc: OrbitalSource;
  gold: OrbitalSource;
}

export interface RelationsModel {
  btc: OrbitalModel;
  gold: OrbitalModel;
  /** Sources propres à BTC (label absent du roster GOLD), ordre du roster. */
  btcOnly: OrbitalSource[];
  /** Sources propres à GOLD, ordre du roster. */
  goldOnly: OrbitalSource[];
  /** Sources présentes dans les DEUX rosters (le « pont »), ordre du roster BTC. */
  shared: SharedRelation[];
}

/**
 * Construit le modèle relations à partir des signaux et de la santé des sources.
 * PUR : aucune dépendance React/RN, aucun effet de bord.
 */
export function buildRelationsModel(
  signals: Signal[] | null,
  health: SourceHealth | null,
): RelationsModel {
  const btc = buildOrbitalModel('BTC', signals, health);
  const gold = buildOrbitalModel('GOLD', signals, health);

  const goldByLabel = new Map(gold.sources.map((s) => [s.label, s]));
  const btcLabels = new Set(btc.sources.map((s) => s.label));

  const shared: SharedRelation[] = [];
  const btcOnly: OrbitalSource[] = [];
  for (const s of btc.sources) {
    const g = goldByLabel.get(s.label);
    if (g) shared.push({ label: s.label, btc: s, gold: g });
    else btcOnly.push(s);
  }
  const goldOnly = gold.sources.filter((s) => !btcLabels.has(s.label));

  return { btc, gold, btcOnly, goldOnly, shared };
}
