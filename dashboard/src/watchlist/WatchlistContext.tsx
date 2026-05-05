/**
 * WatchlistContext — signaux marqués pour follow-up par l'utilisatrice.
 *
 * Phase C reframée OSINT (cf. CLAUDE.md section 8 Paquet 13) :
 *   - Pattern « saved alerts » / « watchlist » standard chez Recorded Future,
 *     Bloomberg Terminal, Dataminr.
 *   - Domain-agnostic : aucune sémantique trading dans les types ou libellés.
 *     Vocabulaire neutre (« suivre », « résultat observé »).
 *   - L'auto-resolution de l'outcome (via track record Phase A.3) viendra en
 *     Session 2. Aujourd'hui, l'entry porte un `outcome: 'pending'` par défaut,
 *     éventuellement override-able manuellement plus tard.
 *
 * Persistance : AsyncStorage clé `tik.watchlist.v1`. Hydratation eager au
 * mount du provider (avant le premier render) ; persistance à chaque
 * changement. Cap MAX_WATCHLIST=200 (volontaire de marquer = pas de spam,
 * cap plus généreux que les alertes WS qui s'accumulent passivement).
 *
 * Cohérent avec AlertsContext (même pattern hydratation/persistance, même
 * filet d'exception JSON corrompu).
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { Signal } from '@/src/api/types';

const MAX_WATCHLIST = 200;
const STORAGE_KEY = 'tik.watchlist.v1';

export type WatchlistOutcome = 'pending' | 'confirmed' | 'refuted' | 'n_a';

/**
 * Snapshot des champs du signal au moment du suivi. On stocke localement
 * pour pouvoir afficher l'entrée même si le signal n'est plus dans la liste
 * /signals (cap 100 côté API, ou expiry passée). Le signal complet reste
 * accessible via getSignal(signalId) pour les détails.
 */
export interface WatchlistEntry {
  signalId: string;
  entityId: string;
  horizon: string;
  direction: string;
  veracity: number;
  confidence: number;
  signalTimestamp: string;
  expiry: string | null;
  circuitBreakerStatus: string;
  addedAt: string;
  outcome: WatchlistOutcome;
  outcomeResolvedAt: string | null;
  userNote: string | null;
}

interface WatchlistContextValue {
  entries: WatchlistEntry[];
  isWatched: (signalId: string) => boolean;
  add: (signal: Signal) => void;
  remove: (signalId: string) => void;
  setOutcome: (signalId: string, outcome: WatchlistOutcome, note?: string | null) => void;
  clear: () => void;
  hydrated: boolean;
}

const WatchlistContext = createContext<WatchlistContextValue | null>(null);

function buildEntry(signal: Signal): WatchlistEntry {
  return {
    signalId: signal.id,
    entityId: signal.entity_id,
    horizon: signal.horizon,
    direction: signal.direction,
    veracity: signal.veracity,
    confidence: signal.confidence,
    signalTimestamp: signal.timestamp,
    expiry: signal.expiry,
    circuitBreakerStatus: signal.circuit_breaker_status,
    addedAt: new Date().toISOString(),
    outcome: 'pending',
    outcomeResolvedAt: null,
    userNote: null,
  };
}

export function WatchlistProvider({ children }: { children: ReactNode }) {
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
  const [hydrated, setHydrated] = useState(false);

  // Hydratation eager au mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        if (cancelled) return;
        if (raw) {
          const parsed = JSON.parse(raw) as WatchlistEntry[];
          if (Array.isArray(parsed)) {
            setEntries((current) =>
              current.length === 0 ? parsed.slice(0, MAX_WATCHLIST) : current,
            );
          }
        }
      } catch (err) {
        console.warn('[WatchlistContext] failed to hydrate from storage, resetting', err);
        try {
          await AsyncStorage.removeItem(STORAGE_KEY);
        } catch {
          /* swallow */
        }
      } finally {
        if (!cancelled) setHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Persistance à chaque changement, mais seulement après l'hydratation pour
  // ne pas écraser le storage avec [] au boot.
  useEffect(() => {
    if (!hydrated) return;
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(entries)).catch((err) => {
      console.warn('[WatchlistContext] failed to persist to storage', err);
    });
  }, [entries, hydrated]);

  const isWatched = useCallback(
    (signalId: string) => entries.some((e) => e.signalId === signalId),
    [entries],
  );

  const add = useCallback((signal: Signal) => {
    setEntries((prev) => {
      if (prev.some((e) => e.signalId === signal.id)) return prev;
      const next = [buildEntry(signal), ...prev];
      return next.slice(0, MAX_WATCHLIST);
    });
  }, []);

  const remove = useCallback((signalId: string) => {
    setEntries((prev) => prev.filter((e) => e.signalId !== signalId));
  }, []);

  const setOutcome = useCallback(
    (signalId: string, outcome: WatchlistOutcome, note: string | null = null) => {
      setEntries((prev) =>
        prev.map((e) =>
          e.signalId === signalId
            ? {
                ...e,
                outcome,
                outcomeResolvedAt:
                  outcome === 'pending' ? null : new Date().toISOString(),
                userNote: note ?? e.userNote,
              }
            : e,
        ),
      );
    },
    [],
  );

  const clear = useCallback(() => {
    setEntries([]);
  }, []);

  const value = useMemo<WatchlistContextValue>(
    () => ({ entries, isWatched, add, remove, setOutcome, clear, hydrated }),
    [entries, isWatched, add, remove, setOutcome, clear, hydrated],
  );

  return <WatchlistContext.Provider value={value}>{children}</WatchlistContext.Provider>;
}

export function useWatchlist(): WatchlistContextValue {
  const ctx = useContext(WatchlistContext);
  if (ctx === null)
    throw new Error('useWatchlist must be used inside <WatchlistProvider>');
  return ctx;
}
