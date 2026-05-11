/**
 * Helper Watchlist ↔ POST /feedback.
 *
 * Phase C Session 2 trading manuel J+10 (Paquet 20) — pont entre le
 * vocabulaire OSINT-neutre de la Watchlist (`WatchlistOutcome`) et le
 * vocabulaire trading-historique du backend (`FeedbackOutcome`).
 *
 * Mappings (cohérent core/src/tik_core/storage/schemas.py `FeedbackIn`) :
 *   - confirmed → win
 *   - refuted   → loss
 *   - n_a       → not_taken
 *   - pending   → ne pas submit (skip)
 *
 * Plan stratégique D1 (Paquet 18) : POST /feedback systématique (auto +
 * manuel) pour nourrir la recalibration daily 03:00 UTC des SOURCE_SCORES
 * (ADR-011 source credibility).
 *
 * Tagging via `exit_reason` pour traçabilité ultérieure :
 *   - SOURCE_AUTO   = "auto_market_check" — résolu par track record
 *   - SOURCE_MANUAL = "user_override"     — résolu par tape utilisatrice
 *   - Si une note libre est fournie en override, elle remplace
 *     SOURCE_MANUAL dans exit_reason (la note est plus informative).
 *
 * Best-effort : tout échec HTTP/réseau est loggué en console.warn mais
 * n'interrompt pas le flux UX local. La Watchlist reste utilisable même
 * quand le backend est down (cas réel pendant la période Windows sans
 * Docker — cf. mémoire `project_platform_windows_period.md`).
 */

import { submitFeedback } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { HttpClient } from '@/src/api/client';
import { FeedbackOutcome } from '@/src/api/types';

import { WatchlistOutcome } from './WatchlistContext';

export const FEEDBACK_SOURCE_AUTO = 'auto_market_check';
export const FEEDBACK_SOURCE_MANUAL = 'user_override';

/**
 * Convertit le vocabulaire OSINT-neutre vers le vocabulaire trading du
 * backend. Retourne `null` pour `pending` (rien à submit).
 */
export function watchlistOutcomeToFeedbackOutcome(
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
      // Exhaustivité TypeScript : ce code n'est censé jamais s'exécuter.
      // Si on ajoute une nouvelle valeur à WatchlistOutcome, le compilateur
      // signalera ici qu'il manque un case.
      return null;
  }
}

export interface SubmitWatchlistFeedbackOptions {
  /**
   * Origine de la résolution. Déterminé par le caller :
   *   - 'auto'   : useAutoResolveWatchlist via track record
   *   - 'manual' : OverrideOutcomeModal via tape utilisatrice
   */
  source: 'auto' | 'manual';
  /** Note libre saisie par l'utilisatrice (manuel uniquement, optionnelle). */
  note?: string | null;
}

/**
 * Submit best-effort un outcome de la Watchlist vers POST /api/v1/feedback.
 *
 * Retourne `true` si le submit a réussi (201), `false` sinon (skip, échec
 * réseau, 4xx, etc.). Ne lève **jamais** — le caller décide ce qu'il fait
 * de la valeur de retour (généralement : mettre à jour l'état local
 * dans tous les cas).
 */
export async function submitWatchlistFeedback(
  client: HttpClient,
  signalId: string,
  outcome: WatchlistOutcome,
  opts: SubmitWatchlistFeedbackOptions,
): Promise<boolean> {
  const backendOutcome = watchlistOutcomeToFeedbackOutcome(outcome);
  if (backendOutcome === null) {
    // pending ou valeur inconnue : on skip silencieusement.
    return false;
  }

  // exit_reason : la note libre prime si elle est fournie, sinon on tag par source.
  const trimmedNote = opts.note?.trim() ?? '';
  const exitReason: string =
    trimmedNote.length > 0
      ? trimmedNote
      : opts.source === 'manual'
      ? FEEDBACK_SOURCE_MANUAL
      : FEEDBACK_SOURCE_AUTO;

  try {
    await submitFeedback(client, {
      signal_id: signalId,
      outcome: backendOutcome,
      exit_reason: exitReason,
    });
    return true;
  } catch (err) {
    const msg = err instanceof TikError ? err.message : (err as Error).message;
    console.warn(
      `[watchlist/feedback] submit failed for signal=${signalId} outcome=${outcome} source=${opts.source}: ${msg}`,
    );
    return false;
  }
}
