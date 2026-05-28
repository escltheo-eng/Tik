/**
 * Helpers purs Phase C Session 2 — résolution outcome watchlist depuis
 * le track record signal (Paquet 12 + 17) + mapping vers feedback core
 * (`core/src/tik_core/storage/schemas.py:FeedbackIn`).
 *
 * Aucune dépendance React / Native / IO. Testable trivialement.
 */

import type { FeedbackOutcome, SignalTrackRecord, TrackRecordRow } from '@/src/api/types';
import type { WatchlistOutcome } from './WatchlistContext';

export interface DerivedOutcome {
  outcome: WatchlistOutcome;
  sourceRowLabel: string;
  deltaPct: number | null;
  success: boolean | null;
  badge: string;
}

/** État affiné d'une ligne (réplique `effectiveState` du détail signal). */
type RowState = 'correct' | 'sous_seuil' | 'raté' | 'données_manquantes';

function rowState(row: TrackRecordRow, dir: string): RowState {
  if (row.badge === 'données_manquantes' || row.delta_pct == null) {
    return 'données_manquantes';
  }
  // Signaux neutres : on garde le verdict binaire du backend.
  if (dir !== 'long' && dir !== 'short') {
    return row.badge === 'correct' ? 'correct' : 'raté';
  }
  const gain = dir === 'long' ? row.delta_pct : -row.delta_pct;
  if (gain > row.threshold_pct) return 'correct';
  if (gain < -row.threshold_pct) return 'raté';
  return 'sous_seuil';
}

/**
 * Dérive l'outcome watchlist depuis un track record — FENÊTRE-AWARE.
 *
 * On ne se base plus sur la seule ligne de l'horizon contractuel (qui ratait
 * un flash monté à 30 min puis redescendu à 1h pile). On regarde TOUTES les
 * lignes échues de la fenêtre :
 *   - une ligne au moins atteint ton sens (≥ son seuil)  → confirmed
 *   - aucune dans ton sens MAIS au moins une contre toi   → refuted
 *   - que du sous-seuil (ça a stagné)                     → inconclusive
 *   - que des données manquantes                          → n_a
 *
 * Retourne `null` (reste pending) tant que la fenêtre n'est pas complète
 * (dernière ligne encore en_attente) ou s'il n'y a aucune ligne.
 *
 * Le verdict diverge volontairement du hit rate global (mesuré à l'instant
 * contractuel) : la watchlist répond « le mouvement s'est-il produit pendant
 * la fenêtre », pas « où était le prix à l'instant T ».
 */
export function deriveOutcomeFromTrackRecord(
  record: SignalTrackRecord,
): DerivedOutcome | null {
  const rows = record.rows ?? [];
  if (rows.length === 0) return null;
  // Fenêtre pas encore complète → on attend (le cooldown évite le spam).
  if (rows[rows.length - 1].badge === 'en_attente') return null;

  const dir = record.direction.toLowerCase();
  let firstCorrect: TrackRecordRow | null = null;
  let lastRate: TrackRecordRow | null = null;
  let lastSubThreshold: TrackRecordRow | null = null;
  let anyEvaluable = false;

  for (const row of rows) {
    if (row.badge === 'en_attente') continue;
    const st = rowState(row, dir);
    if (st === 'données_manquantes') continue;
    anyEvaluable = true;
    if (st === 'correct') {
      if (firstCorrect === null) firstCorrect = row;
    } else if (st === 'raté') {
      lastRate = row;
    } else {
      lastSubThreshold = row;
    }
  }

  if (!anyEvaluable) {
    const last = rows[rows.length - 1];
    return {
      outcome: 'n_a',
      sourceRowLabel: last.label,
      deltaPct: last.delta_pct,
      success: null,
      badge: 'données_manquantes',
    };
  }
  if (firstCorrect) {
    return {
      outcome: 'confirmed',
      sourceRowLabel: firstCorrect.label,
      deltaPct: firstCorrect.delta_pct,
      success: true,
      badge: 'correct',
    };
  }
  if (lastRate) {
    return {
      outcome: 'refuted',
      sourceRowLabel: lastRate.label,
      deltaPct: lastRate.delta_pct,
      success: false,
      badge: 'raté',
    };
  }
  // que du sous-seuil → ni gagné ni vraiment perdu
  const ref = lastSubThreshold ?? rows[rows.length - 1];
  return {
    outcome: 'inconclusive',
    sourceRowLabel: ref.label,
    deltaPct: ref.delta_pct,
    success: null,
    badge: 'sous_seuil',
  };
}

/**
 * Mapping watchlist outcome → feedback core outcome.
 *
 * Watchlist vocab : pending / confirmed / refuted / n_a (OSINT-neutral).
 * Feedback core vocab : win / loss / breakeven / not_taken (trading-specific).
 *
 * Mapping :
 *   - confirmed (direction Tik correcte) → win
 *   - refuted (direction Tik incorrecte) → loss
 *   - n_a (data manquante ou explicite non-trading) → not_taken
 *   - inconclusive (mouvement sous le seuil) → null (on N'envoie PAS : ce
 *     n'est ni un win ni un loss, ça polluerait la calibration source)
 *   - pending → null (ne pas envoyer, pas encore résolu)
 *
 * Note : `breakeven` n'est pas exposé par l'auto-resolution car le track
 * record ne fournit pas ce niveau de granularité. Reste accessible via
 * override manuel si une session future étend l'UI.
 */
export function mapOutcomeToFeedback(
  outcome: WatchlistOutcome,
): FeedbackOutcome | null {
  switch (outcome) {
    case 'confirmed':
      return 'win';
    case 'refuted':
      return 'loss';
    case 'n_a':
      return 'not_taken';
    case 'inconclusive':
      return null;
    case 'pending':
      return null;
    default:
      return null;
  }
}

/**
 * Construit un `exit_reason` lisible pour POST /feedback.
 * Permet à un futur post-traitement backend de filtrer auto vs manuel
 * sans modifier le schéma `FeedbackIn` (cf. ADR-003 non-modification API).
 *
 * Exemples produits :
 *   - "watchlist_auto_swing_5j_confirmed"
 *   - "watchlist_manual_flash_override_refuted"
 */
export function formatExitReason(
  source: 'auto' | 'manual',
  signalHorizon: string,
  outcome: WatchlistOutcome,
  rowLabel?: string,
): string {
  if (source === 'auto') {
    return `watchlist_auto_${signalHorizon}_${rowLabel ?? 'unknown'}_${outcome}`;
  }
  return `watchlist_manual_${signalHorizon}_override_${outcome}`;
}

/**
 * Construit un `trade_id` distinctif pour POST /feedback.
 * Préfixe permet de discriminer la source côté DB.
 */
export function formatTradeId(
  source: 'auto' | 'manual',
  signalId: string,
): string {
  return `watchlist-${source}-${signalId}`;
}

/**
 * Estime si l'outcome d'un signal *devrait* être disponible côté backend.
 * Permet de skip les appels API inutiles sur les signaux trop jeunes (row
 * de référence pas encore atteint).
 *
 * Marges de sécurité : on accepte d'appeler 30 min avant la cible théorique
 * (les klines peuvent arriver légèrement avant la fin de la bougie).
 */
export function isOutcomeLikelyAvailable(
  signalTimestamp: string,
  signalHorizon: string,
  now: Date = new Date(),
): boolean {
  const referenceHours = REFERENCE_HOURS_BY_HORIZON[signalHorizon];
  if (referenceHours === undefined) return false;

  const signalDate = new Date(signalTimestamp);
  if (Number.isNaN(signalDate.getTime())) return false;

  const elapsedHours = (now.getTime() - signalDate.getTime()) / (1000 * 60 * 60);
  return elapsedHours >= referenceHours - 0.5; // -30 min de marge
}

/**
 * Heures écoulées avant le row de référence selon l'horizon.
 * Sources : Paquet 17 (granularité adaptée) + ADR-005 (flash TTL 1h).
 */
export const REFERENCE_HOURS_BY_HORIZON: Record<string, number> = {
  flash: 1,
  swing: 5 * 24,
  macro: 90 * 24,
};

/**
 * Cooldown entre 2 tentatives d'auto-resolution sur un même signal.
 * Évite de spammer l'API quand un appel échoue (HTTP 400 flash GOLD,
 * HTTP 404 signal disparu DB, etc.).
 */
export const AUTO_RESOLVE_COOLDOWN_MS = 30 * 60 * 1000; // 30 min

/**
 * Helper : décide si une entry watchlist est éligible à une tentative
 * d'auto-resolution maintenant.
 */
export function isEligibleForAutoResolve(
  entry: {
    outcome: WatchlistOutcome;
    manuallyResolved?: boolean;
    lastAutoAttemptAt?: string | null;
    signalTimestamp: string;
    horizon: string;
  },
  now: Date = new Date(),
): boolean {
  if (entry.outcome !== 'pending') return false;
  if (entry.manuallyResolved) return false;

  if (entry.lastAutoAttemptAt) {
    const last = new Date(entry.lastAutoAttemptAt);
    if (!Number.isNaN(last.getTime())) {
      const elapsedMs = now.getTime() - last.getTime();
      if (elapsedMs < AUTO_RESOLVE_COOLDOWN_MS) return false;
    }
  }

  return isOutcomeLikelyAvailable(entry.signalTimestamp, entry.horizon, now);
}
