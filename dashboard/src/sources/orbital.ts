/**
 * orbital.ts — modèle PUR de la « vue orbitale » des sources (refonte γ).
 *
 * Construit, pour un actif (BTC / GOLD), la liste des sources OSINT qui
 * l'alimentent + leur état, à partir de DONNÉES RÉELLES déjà exposées :
 *   - `source_health` (vivante / en retard / muette + fraîcheur + note) ;
 *   - le dernier signal SWING de l'actif (texte `evidence` verbatim par source).
 *
 * Honnêteté (Axe #1 / ADR-004) : la veracity est une moyenne NON pondérée des
 * biais sources → AUCUNE source n'a « plus de poids » qu'une autre. On n'affiche
 * donc JAMAIS de « pourcentage d'influence » (ce serait un chiffre inventé). On
 * montre seulement des faits : sens du signal, accord global, état des sources,
 * et le texte que chaque source a réellement produit.
 *
 * Module pur (aucun import React / RN) → testable par exécution.
 */

import type { Signal, SourceHealth, SourceHealthItem } from '@/src/api/types';

export type OrbitalEntity = 'BTC' | 'GOLD';
export type OrbitalStatus = 'ok' | 'stale' | 'missing' | 'disabled';

/** Rôle d'une source dans le moteur (sert l'honnêteté de l'affichage). */
export type OrbitalRole = 'overlay' | 'shadow' | 'disabled';

interface OrbitalSourceDef {
  /** Clé dans `source_health` (null pour les sources hors polling Redis). */
  healthName: string | null;
  label: string;
  /** Valeurs possibles de `evidence[].source` pour retrouver le texte réel. */
  evidenceKeys: string[];
  role: OrbitalRole;
  /** Note statique (sources désactivées, absentes de source_health). */
  staticNote?: string;
}

/**
 * Roster STRUCTUREL (stable) des overlays par actif. L'état (vivant/mort) et le
 * texte viennent en LIVE de source_health + evidence — ici on ne fige que la
 * composition du moteur (cf. CLAUDE.md « la vérité empirique » + audit veracity).
 */
const ROSTER: Record<OrbitalEntity, OrbitalSourceDef[]> = {
  BTC: [
    {
      healthName: 'fear_greed',
      label: 'Fear & Greed',
      evidenceKeys: ['alternative_me_fng'],
      role: 'overlay',
    },
    {
      healthName: 'google_news_btc',
      label: 'Google News',
      evidenceKeys: ['google_news_rss'],
      role: 'overlay',
    },
    {
      healthName: 'cryptocompare_news',
      label: 'CryptoCompare',
      evidenceKeys: ['cryptocompare', 'cryptocompare_news'],
      role: 'overlay',
    },
    {
      healthName: 'reddit_btc',
      label: 'Reddit',
      evidenceKeys: ['reddit', 'reddit_btc'],
      role: 'overlay',
    },
    {
      healthName: 'coingecko_btc',
      label: 'CoinGecko',
      evidenceKeys: ['coingecko', 'coingecko_btc'],
      role: 'shadow',
    },
  ],
  GOLD: [
    {
      healthName: 'google_news_gold',
      label: 'Google News',
      evidenceKeys: ['google_news_rss'],
      role: 'overlay',
    },
    {
      healthName: 'gdelt_gold',
      label: 'GDELT',
      evidenceKeys: ['gdelt_news'],
      role: 'overlay',
    },
    {
      healthName: null,
      label: 'DXY',
      evidenceKeys: ['dxy'],
      role: 'disabled',
      staticNote:
        'Désactivé — biais mesuré inversé en marché haussier (ADR-018 P2). Réactivation conditionnée à une re-mesure propre.',
    },
    {
      healthName: null,
      label: 'COT (CFTC)',
      evidenceKeys: ['cot', 'cftc_cot'],
      role: 'disabled',
      staticNote:
        'Désactivé — positionnement CFTC mesuré inversé en marché haussier (ADR-018 P2).',
    },
  ],
};

export interface OrbitalSource {
  label: string;
  role: OrbitalRole;
  status: OrbitalStatus;
  ageSeconds: number | null;
  critical: boolean;
  note: string;
  /** Texte réel produit par la source (evidence verbatim), ou null si absente. */
  fact: string | null;
  /** Crédibilité éditoriale (evidence.score) — N'INFLUE PAS sur l'accord (A12). */
  credibility: number | null;
}

export interface OrbitalModel {
  entity: OrbitalEntity;
  /** Direction du dernier signal SWING (null si aucun récent). */
  direction: string | null;
  /** Accord = veracity (dispersion des sources), ∈ [0,1]. */
  accord: number | null;
  /** Conviction OSINT = confidence, ∈ [0,1]. */
  conviction: number | null;
  signalAt: string | null;
  sources: OrbitalSource[];
  /** Overlays actifs (role=overlay) qui sont vivants (status=ok). */
  nAlive: number;
  /** Overlays attendus (role=overlay) au total. */
  nOverlays: number;
}

function indexHealth(health: SourceHealth | null): Map<string, SourceHealthItem> {
  const m = new Map<string, SourceHealthItem>();
  health?.sources.forEach((s) => m.set(s.name, s));
  return m;
}

/** Premier signal swing de l'actif dans la liste (déjà triée desc par le core). */
function latestSwing(signals: Signal[] | null, entity: OrbitalEntity): Signal | null {
  return (
    (signals ?? []).find((s) => s.entity_id === entity && s.horizon === 'swing') ?? null
  );
}

function indexFacts(signal: Signal | null): Map<string, { fact: string; score: number }> {
  const m = new Map<string, { fact: string; score: number }>();
  signal?.evidence.forEach((e) => {
    if (!m.has(e.source)) m.set(e.source, { fact: e.fact, score: e.score });
  });
  return m;
}

/**
 * Construit le modèle orbital d'un actif à partir des signaux et de la santé des
 * sources. PUR : mêmes entrées → même sortie, aucun effet de bord.
 */
export function buildOrbitalModel(
  entity: OrbitalEntity,
  signals: Signal[] | null,
  health: SourceHealth | null,
): OrbitalModel {
  const defs = ROSTER[entity];
  const healthByName = indexHealth(health);
  const swing = latestSwing(signals, entity);
  const factByKey = indexFacts(swing);

  const sources: OrbitalSource[] = defs.map((def) => {
    const h = def.healthName ? healthByName.get(def.healthName) : undefined;

    let status: OrbitalStatus;
    if (def.role === 'disabled') status = 'disabled';
    else if (!h) status = 'missing';
    else status = h.status;

    let fact: string | null = null;
    let credibility: number | null = null;
    for (const k of def.evidenceKeys) {
      const f = factByKey.get(k);
      if (f) {
        fact = f.fact;
        credibility = f.score;
        break;
      }
    }

    return {
      label: def.label,
      role: def.role,
      status,
      ageSeconds: h?.age_seconds ?? null,
      critical: h?.critical ?? false,
      note: def.staticNote ?? h?.note ?? '',
      fact,
      credibility,
    };
  });

  const overlays = sources.filter((s) => s.role === 'overlay');
  const nAlive = overlays.filter((s) => s.status === 'ok').length;

  return {
    entity,
    direction: swing?.direction ?? null,
    accord: swing?.veracity ?? null,
    conviction: swing?.confidence ?? null,
    signalAt: swing?.timestamp ?? null,
    sources,
    nAlive,
    nOverlays: overlays.length,
  };
}

/** Libellé court d'un statut (affichage). */
export function statusLabel(s: OrbitalStatus): string {
  switch (s) {
    case 'ok':
      return 'Vivante';
    case 'stale':
      return 'En retard';
    case 'disabled':
      return 'Désactivée';
    default:
      return 'Muette';
  }
}

/** Âge humain (FR) d'une fraîcheur en secondes. */
export function ageLabel(age: number | null): string {
  if (age == null) return 'jamais reçue';
  if (age < 60) return `il y a ${Math.round(age)} s`;
  if (age < 3600) return `il y a ${Math.round(age / 60)} min`;
  if (age < 86400) return `il y a ${Math.round(age / 3600)} h`;
  return `il y a ${Math.round(age / 86400)} j`;
}
