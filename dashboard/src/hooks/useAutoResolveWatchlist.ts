/**
 * useAutoResolveWatchlist — résout automatiquement les entries `pending`
 * de la Watchlist via le track record du signal (Phase A.3 Paquet 12).
 *
 * Phase C Session 2 trading manuel J+10 (Paquet 20).
 *
 * Décisions structurantes (cf. CLAUDE.md Paquet 20 décisions D1-D2) :
 *   - D1 : poll throttlé déclenché à l'ouverture du tab Watchlist + refresh
 *     toutes 5 min (évite background polling qui draine la batterie iPhone).
 *   - D2 : on lit **uniquement la dernière row du track record** (celle qui
 *     match le TTL contractuel du signal). Flash : row 1h. Swing : row 5d.
 *     Macro : row 90d. Si cette row est `available && badge≠"en_attente"`,
 *     on résout. Sinon on laisse pending.
 *
 * Throttle : `MAX_PARALLEL_FETCHES=20` par cycle (évite de spammer le core
 * si la Watchlist est large + cap MAX_WATCHLIST=200).
 *
 * Best-effort intégral : tout échec HTTP (network down, 404 signal trop
 * vieux pour avoir un track record, etc.) → l'entry reste `pending`,
 * un warning est loggué, le hook continue avec la suivante.
 *
 * Pour chaque entry résolue :
 *   1. Mapping `badge → WatchlistOutcome`
 *   2. setOutcome local (immédiat)
 *   3. submitWatchlistFeedback(source='auto') best-effort POST /feedback
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getSignalTrackRecord } from '@/src/api/endpoints';
import { useAuth } from '@/src/auth/AuthContext';
import { useWatchlist, type WatchlistEntry, type WatchlistOutcome } from '@/src/watchlist/WatchlistContext';
import { submitWatchlistFeedback } from '@/src/watchlist/feedback';

const AUTO_REFRESH_INTERVAL_MS = 5 * 60 * 1000; // 5 min
const MAX_PARALLEL_FETCHES = 20;

/**
 * Mapping badge backend → outcome OSINT-neutre.
 * Cohérent `dashboard/src/api/types.ts` `TrackRecordBadge`.
 */
function badgeToOutcome(badge: string): WatchlistOutcome {
  switch (badge) {
    case 'correct':
      return 'confirmed';
    case 'raté':
      return 'refuted';
    case 'données_manquantes':
      return 'n_a';
    case 'en_attente':
    default:
      return 'pending';
  }
}

export interface UseAutoResolveWatchlistResult {
  /** True pendant qu'un cycle de résolution est en cours. */
  resolving: boolean;
  /** Nb d'entries résolues lors du dernier cycle (UI feedback). */
  lastResolvedCount: number;
  /** Date ISO du dernier cycle terminé (null si jamais). */
  lastRunAt: string | null;
  /** Trigger manuel d'un cycle (bouton refresh par exemple). */
  refresh: () => Promise<void>;
}

/**
 * Tourne automatiquement quand le hook est monté (= tab Watchlist ouvert)
 * et toutes les 5 min ensuite. Si l'utilisatrice ferme le tab, le hook
 * démonte et tout s'arrête (pas de fuite de timers).
 */
export function useAutoResolveWatchlist(): UseAutoResolveWatchlistResult {
  const { client, apiKey } = useAuth();
  const { entries, setOutcome } = useWatchlist();
  const [resolving, setResolving] = useState(false);
  const [lastResolvedCount, setLastResolvedCount] = useState(0);
  const [lastRunAt, setLastRunAt] = useState<string | null>(null);

  // Référence stable aux entries pour ne pas re-créer le callback à chaque
  // changement de Watchlist (sinon le setInterval se recréerait).
  const entriesRef = useRef<WatchlistEntry[]>(entries);
  useEffect(() => {
    entriesRef.current = entries;
  }, [entries]);

  // Mutex pour éviter qu'un cycle se chevauche avec lui-même (par exemple si
  // l'utilisatrice tape refresh pendant qu'un cycle est en cours).
  const runningRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    if (runningRef.current) return;
    runningRef.current = true;
    setResolving(true);

    try {
      const pending = entriesRef.current
        .filter((e) => e.outcome === 'pending')
        .slice(0, MAX_PARALLEL_FETCHES);

      if (pending.length === 0) {
        setLastResolvedCount(0);
        setLastRunAt(new Date().toISOString());
        return;
      }

      // Promise.allSettled : on traite chaque entry indépendamment, un échec
      // n'arrête pas les autres.
      const results = await Promise.allSettled(
        pending.map(async (entry) => {
          const tr = await getSignalTrackRecord(client, entry.signalId);
          return { entry, trackRecord: tr };
        }),
      );

      let resolvedCount = 0;

      for (let i = 0; i < results.length; i += 1) {
        const result = results[i];
        if (result.status !== 'fulfilled') {
          // 404 (signal trop vieux) ou network error → on laisse pending, on
          // réessayera au prochain cycle.
          continue;
        }
        const { entry, trackRecord } = result.value;
        // D2 — on regarde uniquement la dernière row (= TTL contractuel du signal).
        const lastRow = trackRecord.rows[trackRecord.rows.length - 1];
        if (!lastRow || !lastRow.available) continue;
        const newOutcome = badgeToOutcome(lastRow.badge);
        if (newOutcome === 'pending') continue;

        // 1. Update local immédiat.
        setOutcome(entry.signalId, newOutcome, null);
        resolvedCount += 1;

        // 2. POST /feedback best-effort (non-bloquant — le caller continue).
        void submitWatchlistFeedback(client, entry.signalId, newOutcome, {
          source: 'auto',
        });
      }

      setLastResolvedCount(resolvedCount);
      setLastRunAt(new Date().toISOString());
    } finally {
      runningRef.current = false;
      setResolving(false);
    }
  }, [client, apiKey, setOutcome]);

  // Premier run au mount + refresh régulier.
  useEffect(() => {
    if (!apiKey) return;
    void refresh();
    const id = setInterval(() => {
      void refresh();
    }, AUTO_REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [apiKey, refresh]);

  return { resolving, lastResolvedCount, lastRunAt, refresh };
}
