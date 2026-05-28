/**
 * useAutoResolveWatchlist — Phase C Session 2 (Paquet 28).
 *
 * Résout automatiquement l'outcome des entries watchlist en `pending` :
 *   1. Filtre les entries éligibles (pending + pas manuel + post-cooldown
 *      + row de référence théoriquement atteint).
 *   2. Trie par addedAt ASC (priorise les plus anciennes).
 *   3. Cap N entries par cycle (default 20) → évite de spammer le core.
 *   4. Pour chaque entry, fetch `getSignalTrackRecord` → `deriveOutcomeFromTrackRecord`.
 *   5. Si outcome dérivé non-null → `setOutcomeAuto` + fire-and-forget
 *      `reportFeedback` (swallow 401/403 si scope manquant).
 *   6. Sinon → `markAutoAttempt` avec error.
 *
 * Lifecycle :
 *   - 1 cycle one-shot au boot du hook (premier mount où isAuthenticated
 *     devient true).
 *   - 1 cycle au focus de l'écran appelant (via `runOnce`).
 *   - Interval `pollIntervalMs` (default 5 min) tant que `enabled=true`.
 *
 * Non-bloquant : tous les appels API sont en best-effort. Les erreurs sont
 * loggées + tracées dans l'entry mais ne propagent jamais d'exception
 * vers le composant appelant.
 */

import { useCallback, useEffect, useRef } from 'react';

import { getSignalTrackRecord, reportFeedback } from '@/src/api/endpoints';
import type { HttpClient } from '@/src/api/client';
import {
  AUTO_RESOLVE_COOLDOWN_MS,
  deriveOutcomeFromTrackRecord,
  formatExitReason,
  formatTradeId,
  isEligibleForAutoResolve,
  mapOutcomeToFeedback,
} from './outcome';
import { useWatchlist, type WatchlistEntry } from './WatchlistContext';

const DEFAULT_POLL_INTERVAL_MS = 5 * 60 * 1000; // 5 min
const DEFAULT_MAX_PER_CYCLE = 20;

export interface UseAutoResolveWatchlistOptions {
  /** Désactive complètement le hook (default true). */
  enabled?: boolean;
  /** Intervalle entre 2 cycles auto (default 5 min). */
  pollIntervalMs?: number;
  /** Nombre max d'entries traitées par cycle (default 20). */
  maxPerCycle?: number;
  /** Cooldown entre 2 tentatives sur la même entry (default 30 min). */
  cooldownMs?: number;
}

export interface UseAutoResolveWatchlistApi {
  /** Lance un cycle de résolution maintenant. Idempotent (re-entrant safe). */
  runOnce: () => Promise<void>;
  /** True pendant qu'un cycle est en cours. */
  busy: boolean;
}

export function useAutoResolveWatchlist(
  client: HttpClient,
  isAuthenticated: boolean,
  options: UseAutoResolveWatchlistOptions = {},
): UseAutoResolveWatchlistApi {
  const {
    enabled = true,
    pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
    maxPerCycle = DEFAULT_MAX_PER_CYCLE,
    cooldownMs = AUTO_RESOLVE_COOLDOWN_MS,
  } = options;

  const { entries, setOutcomeAuto, markAutoAttempt, hydrated } = useWatchlist();

  // Refs pour casser les closures stales dans les callbacks asynchrones.
  const entriesRef = useRef(entries);
  entriesRef.current = entries;
  const setOutcomeAutoRef = useRef(setOutcomeAuto);
  setOutcomeAutoRef.current = setOutcomeAuto;
  const markAutoAttemptRef = useRef(markAutoAttempt);
  markAutoAttemptRef.current = markAutoAttempt;
  const clientRef = useRef(client);
  clientRef.current = client;
  const busyRef = useRef(false);

  const runOnce = useCallback(async () => {
    if (busyRef.current) return;
    if (!isAuthenticated) return;
    if (!hydrated) return;

    const now = new Date();
    const eligible = entriesRef.current
      .filter((e) =>
        isEligibleForAutoResolve(
          {
            outcome: e.outcome,
            manuallyResolved: e.manuallyResolved,
            lastAutoAttemptAt: e.lastAutoAttemptAt,
            signalTimestamp: e.signalTimestamp,
            horizon: e.horizon,
          },
          now,
        ),
      )
      // Helper pur a déjà appliqué le cooldown via lastAutoAttemptAt.
      // On respecte ici un cooldownMs custom si différent du default.
      .filter((e) => {
        if (!e.lastAutoAttemptAt) return true;
        const last = new Date(e.lastAutoAttemptAt).getTime();
        return now.getTime() - last >= cooldownMs;
      })
      .sort((a, b) => a.addedAt.localeCompare(b.addedAt))
      .slice(0, maxPerCycle);

    if (eligible.length === 0) return;

    busyRef.current = true;
    try {
      const resolve = createResolveEntryFn({
        client: clientRef.current,
        setOutcomeAuto: setOutcomeAutoRef.current,
        markAutoAttempt: markAutoAttemptRef.current,
      });
      // Appels parallèles. Promise.allSettled : on continue même si
      // certaines rejettent (chaque entry gère son erreur localement
      // via markAutoAttempt → cooldown 30 min).
      await Promise.allSettled(eligible.map((entry) => resolve(entry)));
    } finally {
      busyRef.current = false;
    }
  }, [isAuthenticated, hydrated, cooldownMs, maxPerCycle]);

  // 1 cycle one-shot au boot (premier mount où hydrated + authenticated devient true).
  useEffect(() => {
    if (!enabled) return;
    if (!hydrated) return;
    if (!isAuthenticated) return;
    runOnce().catch((err) => {
      console.warn('[useAutoResolveWatchlist] boot cycle failed', err);
    });
    // Volontairement pas de dep sur runOnce (changerait à chaque hydrate)
    // — on veut un seul tir au boot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, hydrated, isAuthenticated]);

  // Interval périodique tant que enabled.
  useEffect(() => {
    if (!enabled) return;
    if (!hydrated) return;
    if (!isAuthenticated) return;

    const id = setInterval(() => {
      runOnce().catch((err) => {
        console.warn('[useAutoResolveWatchlist] periodic cycle failed', err);
      });
    }, pollIntervalMs);

    return () => clearInterval(id);
  }, [enabled, hydrated, isAuthenticated, pollIntervalMs, runOnce]);

  return {
    runOnce,
    busy: busyRef.current,
  };
}

/**
 * Factory qui matérialise la closure de résolution avec les setters
 * Context capturés. Exposée pour facilité de tests futurs (Session 3).
 *
 * Erreurs API swallowed (loggées + tracées dans l'entry via
 * markAutoAttempt). Toujours résout (jamais reject) — utilisable
 * directement dans `Promise.allSettled`.
 */
export function createResolveEntryFn(deps: {
  client: HttpClient;
  setOutcomeAuto: (
    signalId: string,
    outcome: 'confirmed' | 'refuted' | 'inconclusive' | 'n_a' | 'pending',
    error: string | null,
  ) => void;
  markAutoAttempt: (signalId: string, error: string | null) => void;
}) {
  return async function resolve(entry: WatchlistEntry): Promise<void> {
    try {
      const record = await getSignalTrackRecord(deps.client, entry.signalId);
      const derived = deriveOutcomeFromTrackRecord(record);

      if (derived === null) {
        // Row de référence encore en_attente → on note l'attempt mais
        // garde pending. Le cooldown évitera de re-spam.
        deps.markAutoAttempt(entry.signalId, null);
        return;
      }

      // 1) Persistance locale (immédiat, visible UI).
      deps.setOutcomeAuto(entry.signalId, derived.outcome, null);

      // 2) Fire-and-forget POST /feedback (non-bloquant).
      const feedbackOutcome = mapOutcomeToFeedback(derived.outcome);
      if (feedbackOutcome !== null) {
        const payload = {
          signal_id: entry.signalId,
          trade_id: formatTradeId('auto', entry.signalId),
          outcome: feedbackOutcome,
          exit_reason: formatExitReason(
            'auto',
            entry.horizon,
            derived.outcome,
            derived.sourceRowLabel,
          ),
          pnl_pct: derived.deltaPct,
        };
        reportFeedback(deps.client, payload).catch((err) => {
          // 401/403 = scope manquant côté API key. On swallow + log.
          // Pas de retry — la prochaine auto-resolution (cooldown 30 min)
          // ne renverra pas le feedback (manuallyResolved=false mais
          // outcome != pending → isEligibleForAutoResolve = false).
          console.warn(
            `[useAutoResolveWatchlist] POST /feedback failed (silently) for ${entry.signalId}:`,
            (err as Error).message,
          );
        });
      }
    } catch (err) {
      const code = errorCode(err);
      deps.markAutoAttempt(entry.signalId, code);
      console.warn(
        `[useAutoResolveWatchlist] getSignalTrackRecord failed for ${entry.signalId}: ${code}`,
      );
    }
  };
}

function errorCode(err: unknown): string {
  const e = err as { message?: string; name?: string };
  return e?.name ? `${e.name}: ${e.message ?? ''}` : String(err).slice(0, 100);
}
