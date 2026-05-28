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

export type WatchlistOutcome = 'pending' | 'confirmed' | 'refuted' | 'inconclusive' | 'n_a';

/**
 * Snapshot des champs du signal au moment du suivi. On stocke localement
 * pour pouvoir afficher l'entrée même si le signal n'est plus dans la liste
 * /signals (cap 100 côté API, ou expiry passée). Le signal complet reste
 * accessible via getSignal(signalId) pour les détails.
 *
 * Session 2 (2026-05-19) — Auto-resolution :
 *   - `manuallyResolved` : si true, l'auto-resolution ne touchera jamais
 *     cette entry (l'humain a tranché).
 *   - `lastAutoAttemptAt` : ISO datetime du dernier appel API d'auto-
 *     resolution (succès ou échec) ; permet le cooldown 30 min.
 *   - `autoResolveError` : code de la dernière erreur API (ex. "HTTP 400",
 *     "HTTP 404") pour observabilité. null si pas d'erreur.
 *   - Les entries v1 (Session 1) hydratées depuis storage n'ont pas ces
 *     champs → defaults appliqués au hydrate (cf. `normalizeEntry`).
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
  // Session 2
  manuallyResolved: boolean;
  lastAutoAttemptAt: string | null;
  autoResolveError: string | null;
}

interface WatchlistContextValue {
  entries: WatchlistEntry[];
  isWatched: (signalId: string) => boolean;
  add: (signal: Signal) => void;
  remove: (signalId: string) => void;
  /**
   * Override manuel par l'utilisatrice (tap sur le badge outcome).
   * Marque `manuallyResolved=true` → l'auto-resolution ne touchera plus
   * jamais cette entry.
   */
  setOutcome: (signalId: string, outcome: WatchlistOutcome, note?: string | null) => void;
  /**
   * Résolution automatique via `getSignalTrackRecord` (Session 2).
   * Ne touche pas `manuallyResolved` (reste false). Met à jour
   * `lastAutoAttemptAt` même si le row est encore en_attente (cooldown).
   */
  setOutcomeAuto: (
    signalId: string,
    outcome: WatchlistOutcome | 'pending',
    error: string | null,
  ) => void;
  /**
   * Marque l'attempt d'auto-resolution comme tenté (mise à jour
   * `lastAutoAttemptAt` + `autoResolveError`) sans changer l'outcome.
   * Utilisé quand le row de référence est encore `en_attente` ou en cas
   * d'erreur API → on attend le cooldown.
   */
  markAutoAttempt: (signalId: string, error: string | null) => void;
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
    manuallyResolved: false,
    lastAutoAttemptAt: null,
    autoResolveError: null,
  };
}

/**
 * Compat hydratation : les entries Session 1 (`tik.watchlist.v1`) n'ont
 * pas les champs Session 2. Defaults appliqués sans bumper la clé storage
 * (rétrocompat transparente).
 */
function normalizeEntry(raw: Partial<WatchlistEntry> & { signalId: string }): WatchlistEntry {
  return {
    signalId: raw.signalId,
    entityId: raw.entityId ?? '',
    horizon: raw.horizon ?? 'swing',
    direction: raw.direction ?? 'neutral',
    veracity: raw.veracity ?? 0,
    confidence: raw.confidence ?? 0,
    signalTimestamp: raw.signalTimestamp ?? new Date().toISOString(),
    expiry: raw.expiry ?? null,
    circuitBreakerStatus: raw.circuitBreakerStatus ?? 'ok',
    addedAt: raw.addedAt ?? new Date().toISOString(),
    outcome: raw.outcome ?? 'pending',
    outcomeResolvedAt: raw.outcomeResolvedAt ?? null,
    userNote: raw.userNote ?? null,
    manuallyResolved: raw.manuallyResolved ?? false,
    lastAutoAttemptAt: raw.lastAutoAttemptAt ?? null,
    autoResolveError: raw.autoResolveError ?? null,
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
          const parsed = JSON.parse(raw) as (Partial<WatchlistEntry> & { signalId: string })[];
          if (Array.isArray(parsed)) {
            const normalized = parsed
              .filter((e) => typeof e?.signalId === 'string' && e.signalId.length > 0)
              .map(normalizeEntry)
              .slice(0, MAX_WATCHLIST);
            setEntries((current) => (current.length === 0 ? normalized : current));
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
                manuallyResolved: outcome !== 'pending',
              }
            : e,
        ),
      );
    },
    [],
  );

  const setOutcomeAuto = useCallback(
    (
      signalId: string,
      outcome: WatchlistOutcome | 'pending',
      error: string | null,
    ) => {
      setEntries((prev) =>
        prev.map((e) => {
          if (e.signalId !== signalId) return e;
          if (e.manuallyResolved) return e; // sanctuaire : auto ne touche jamais
          const now = new Date().toISOString();
          if (outcome === 'pending') {
            return {
              ...e,
              lastAutoAttemptAt: now,
              autoResolveError: error,
            };
          }
          return {
            ...e,
            outcome,
            outcomeResolvedAt: now,
            lastAutoAttemptAt: now,
            autoResolveError: null,
            manuallyResolved: false,
          };
        }),
      );
    },
    [],
  );

  const markAutoAttempt = useCallback((signalId: string, error: string | null) => {
    setEntries((prev) =>
      prev.map((e) =>
        e.signalId === signalId
          ? { ...e, lastAutoAttemptAt: new Date().toISOString(), autoResolveError: error }
          : e,
      ),
    );
  }, []);

  const clear = useCallback(() => {
    setEntries([]);
  }, []);

  const value = useMemo<WatchlistContextValue>(
    () => ({
      entries,
      isWatched,
      add,
      remove,
      setOutcome,
      setOutcomeAuto,
      markAutoAttempt,
      clear,
      hydrated,
    }),
    [
      entries,
      isWatched,
      add,
      remove,
      setOutcome,
      setOutcomeAuto,
      markAutoAttempt,
      clear,
      hydrated,
    ],
  );

  return <WatchlistContext.Provider value={value}>{children}</WatchlistContext.Provider>;
}

export function useWatchlist(): WatchlistContextValue {
  const ctx = useContext(WatchlistContext);
  if (ctx === null)
    throw new Error('useWatchlist must be used inside <WatchlistProvider>');
  return ctx;
}
