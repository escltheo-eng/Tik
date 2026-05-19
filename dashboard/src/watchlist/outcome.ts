/**
 * Helpers purs Phase C Session 2 — résolution outcome watchlist depuis
 * le track record signal (Paquet 12 + 17) + mapping vers feedback core
 * (`core/src/tik_core/storage/schemas.py:FeedbackIn`).
 *
 * Aucune dépendance React / Native / IO. Testable trivialement.
 */

import type { FeedbackOutcome, SignalTrackRecord, TrackRecordRow } from '@/src/api/types';
import type { WatchlistOutcome } from './WatchlistContext';

/**
 * Mapping horizon signal → label du row de référence (row le plus long de
 * la fenêtre TTL contractuelle) qui détermine l'outcome final.
 *
 * Cohérent Paquet 17 (granularité adaptée par horizon) :
 *   - flash : 15min / 30min / 45min / 1h → row final = 1h (TTL signal = 1h)
 *   - swing : 1h / 6h / 24h / 5j → row final = 5j (sweet spot mesuré Paquet 1.x)
 *   - macro : 1j / 7j / 30j / 90j → row final = 90j
 */
export const REFERENCE_ROW_BY_HORIZON: Record<string, string> = {
  flash: '1h',
  swing: '5j',
  macro: '90j',
};

export interface DerivedOutcome {
  outcome: WatchlistOutcome;
  sourceRowLabel: string;
  deltaPct: number | null;
  success: boolean | null;
  badge: string;
}

/**
 * Dérive l'outcome watchlist depuis un track record. Retourne `null` si
 * le row de référence n'est pas encore résolu (en_attente).
 *
 * Mapping :
 *   - row.badge === 'correct' (success=true) → confirmed
 *   - row.badge === 'raté' (success=false) → refuted
 *   - row.badge === 'données_manquantes' → n_a (résolu mais data indisponible)
 *   - row.badge === 'en_attente' → null (pas de résolution, reste pending)
 *
 * Cas dégradés :
 *   - Pas de row matching → null (rare, défense)
 *   - Horizon inconnu → null
 */
export function deriveOutcomeFromTrackRecord(
  record: SignalTrackRecord,
): DerivedOutcome | null {
  const refLabel = REFERENCE_ROW_BY_HORIZON[record.horizon];
  if (!refLabel) return null;

  const row = record.rows.find((r) => r.label === refLabel);
  if (!row) return null;

  return mapRowToOutcome(row);
}

/**
 * Helper interne. Exposé pour tests + cas edge où on aurait directement
 * un `TrackRecordRow` (ex. inspection manuelle).
 */
export function mapRowToOutcome(row: TrackRecordRow): DerivedOutcome | null {
  switch (row.badge) {
    case 'correct':
      return {
        outcome: 'confirmed',
        sourceRowLabel: row.label,
        deltaPct: row.delta_pct,
        success: row.success,
        badge: row.badge,
      };
    case 'raté':
      return {
        outcome: 'refuted',
        sourceRowLabel: row.label,
        deltaPct: row.delta_pct,
        success: row.success,
        badge: row.badge,
      };
    case 'données_manquantes':
      return {
        outcome: 'n_a',
        sourceRowLabel: row.label,
        deltaPct: row.delta_pct,
        success: row.success,
        badge: row.badge,
      };
    case 'en_attente':
      return null;
    default:
      return null;
  }
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
