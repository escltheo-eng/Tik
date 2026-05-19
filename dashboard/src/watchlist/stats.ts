/**
 * Helpers purs de stats hit rate perso (Phase C Session 2, Paquet 28).
 *
 * Aucune dépendance React / API / IO. Testable trivialement.
 */

import type { WatchlistEntry } from './WatchlistContext';

export interface PersonalHitRateStats {
  /** Nombre total d'entries (tous outcomes). */
  total: number;
  /** Nombre d'entries non encore résolues (outcome === 'pending'). */
  pending: number;
  /** Nombre d'entries résolues (toutes, y compris n_a). */
  resolved: number;
  /**
   * Nombre d'entries résolues *avec verdict directionnel* :
   * confirmed + refuted. Exclut n_a (data manquante / non-trading).
   * C'est le dénominateur du hit rate perso.
   */
  evaluable: number;
  /** Nombre d'entries `confirmed` (numérateur du hit rate). */
  confirmed: number;
  /** Nombre d'entries `refuted`. */
  refuted: number;
  /** Nombre d'entries `n_a`. */
  na: number;
  /**
   * Hit rate ∈ [0, 1] = confirmed / evaluable. `null` si evaluable = 0
   * (pas encore de signal résolu avec verdict).
   */
  hitRate: number | null;
  /**
   * Nombre d'entries résolues manuellement par l'utilisatrice (override).
   * Pour la transparence : si élevé, le hit rate reflète son jugement
   * post-event plus que le track record auto.
   */
  manuallyResolvedCount: number;
}

const SELECTION_BIAS_THRESHOLD = 20; // <20 résolus = biais de sélection probable

export function computePersonalStats(entries: WatchlistEntry[]): PersonalHitRateStats {
  let pending = 0;
  let confirmed = 0;
  let refuted = 0;
  let na = 0;
  let manuallyResolvedCount = 0;

  for (const e of entries) {
    switch (e.outcome) {
      case 'pending':
        pending += 1;
        break;
      case 'confirmed':
        confirmed += 1;
        break;
      case 'refuted':
        refuted += 1;
        break;
      case 'n_a':
        na += 1;
        break;
    }
    if (e.manuallyResolved) manuallyResolvedCount += 1;
  }

  const total = entries.length;
  const resolved = confirmed + refuted + na;
  const evaluable = confirmed + refuted;
  const hitRate = evaluable > 0 ? confirmed / evaluable : null;

  return {
    total,
    pending,
    resolved,
    evaluable,
    confirmed,
    refuted,
    na,
    hitRate,
    manuallyResolvedCount,
  };
}

/**
 * Renvoie un message d'avertissement si l'échantillon est trop faible
 * pour tirer une conclusion fiable. `null` sinon.
 */
export function selectionBiasWarning(stats: PersonalHitRateStats): string | null {
  if (stats.evaluable === 0) {
    return 'Aucun signal résolu avec verdict directionnel. Patiente que le track record arrive à maturité.';
  }
  if (stats.evaluable < SELECTION_BIAS_THRESHOLD) {
    return `Échantillon limité (${stats.evaluable} résolus avec verdict, < ${SELECTION_BIAS_THRESHOLD}). Biais de sélection possible — tu choisis quels signaux suivre.`;
  }
  return null;
}

export interface HorizonBreakdown {
  flash: number;
  swing: number;
  macro: number;
}

/**
 * Renvoie la distribution des entries par horizon (utile pour décider
 * quel horizon prendre comme référence pour le Tik global comparable).
 */
export function entriesByHorizon(entries: WatchlistEntry[]): HorizonBreakdown {
  let flash = 0;
  let swing = 0;
  let macro = 0;
  for (const e of entries) {
    if (e.horizon === 'flash') flash += 1;
    else if (e.horizon === 'swing') swing += 1;
    else if (e.horizon === 'macro') macro += 1;
  }
  return { flash, swing, macro };
}

/**
 * Horizon "dominant" dans la watchlist (le plus représenté). Utilisé pour
 * choisir le hit rate global Tik comparable. Si tie, ordre de préférence :
 * swing > flash > macro (swing reste l'horizon principal Tik au J+14).
 */
export function dominantHorizon(entries: WatchlistEntry[]): 'flash' | 'swing' | 'macro' | null {
  const b = entriesByHorizon(entries);
  const total = b.flash + b.swing + b.macro;
  if (total === 0) return null;
  if (b.swing >= b.flash && b.swing >= b.macro) return 'swing';
  if (b.flash >= b.macro) return 'flash';
  return 'macro';
}

/**
 * Entity "dominante" dans la watchlist (BTC ou GOLD le plus représenté).
 */
export function dominantEntity(entries: WatchlistEntry[]): string | null {
  const counts: Record<string, number> = {};
  for (const e of entries) {
    counts[e.entityId] = (counts[e.entityId] ?? 0) + 1;
  }
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return sorted.length > 0 ? sorted[0][0] : null;
}
