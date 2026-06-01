/**
 * useSignalStream — hook React qui consomme le flux WS de signaux.
 *
 * Pré-charge les derniers signaux via `getLatestSignals()` au mount, puis
 * ouvre une WebSocket vers `/api/v1/ws/signals` pour recevoir les nouveaux
 * en temps réel.
 *
 * Garde au plus `maxSignals` (défaut 100) en mémoire. Les signaux sont
 * triés du plus récent au plus ancien.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, type AppStateStatus } from 'react-native';

import { getLatestSignals, searchSignals } from '@/src/api/endpoints';
import { ConnectionState, TikStream } from '@/src/api/stream';
import { Signal } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';
import { parseUtcIso } from '@/src/utils/time';

export interface UseSignalStreamOptions {
  entity?: string;
  horizon?: string;
  maxSignals?: number;
  preloadLimit?: number;
  /**
   * Fenêtre temporelle de preload en heures. Si fourni, bascule sur
   * `/signals` (search) au lieu de `/signals/latest` pour accéder à
   * l'historique au-delà de 24h. Valeurs typiques : 24 (défaut),
   * 120 (5 jours), 720 (30 jours). Plafonné côté backend à 720h.
   */
  sinceHours?: number;
}

export interface UseSignalStreamResult {
  signals: Signal[];
  connectionState: ConnectionState;
  error: string | null;
  preloadLoading: boolean;
  preloadError: string | null;
  /**
   * Rattrapage manuel (pull-to-refresh) : re-fetch REST + merge, sans
   * réinitialiser la liste. Résout la promesse à la fin du fetch pour piloter
   * un RefreshControl côté écran. Stable entre les renders.
   */
  refresh: () => Promise<void>;
}

const DEFAULT_MAX_SIGNALS = 100;
const DEFAULT_PRELOAD_LIMIT = 20;

export function useSignalStream(options: UseSignalStreamOptions = {}): UseSignalStreamResult {
  const { client, baseUrl, apiKey } = useAuth();
  const { entity, horizon, sinceHours } = options;
  const maxSignals = options.maxSignals ?? DEFAULT_MAX_SIGNALS;
  const preloadLimit = options.preloadLimit ?? DEFAULT_PRELOAD_LIMIT;

  const [signals, setSignals] = useState<Signal[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [preloadLoading, setPreloadLoading] = useState<boolean>(false);
  const [preloadError, setPreloadError] = useState<string | null>(null);

  const streamRef = useRef<TikStream | null>(null);
  // Pointe vers le `resync` de l'effet courant (recréé quand les filtres
  // changent). Permet d'exposer un `refresh` stable sans recréer le callback.
  const resyncRef = useRef<() => Promise<void>>(async () => {});

  const refresh = useCallback(() => resyncRef.current(), []);

  useEffect(() => {
    let cancelled = false;

    // Live WS : prepend, dédup par id (préserve l'ordre récent → ancien).
    const addSignal = (incoming: Signal) => {
      if (cancelled) return;
      setSignals((prev) => {
        const filtered = prev.filter((s) => s.id !== incoming.id);
        const merged = [incoming, ...filtered];
        return merged.slice(0, maxSignals);
      });
    };

    // Rattrapage REST : fusionne les signaux fraîchement fetchés AVEC ceux déjà
    // en mémoire (sans écraser les live reçus par WS), dédup par id, re-trie du
    // plus récent au plus ancien, cap maxSignals. Sert à combler les signaux
    // émis pendant une coupure WS (écran éteint / app en arrière-plan).
    const mergeInto = (incoming: Signal[]) => {
      if (cancelled) return;
      setSignals((prev) => {
        const byId = new Map<string, Signal>();
        for (const s of incoming) byId.set(s.id, s);
        for (const s of prev) if (!byId.has(s.id)) byId.set(s.id, s);
        const all = Array.from(byId.values());
        all.sort(
          (a, b) => parseUtcIso(b.timestamp).getTime() - parseUtcIso(a.timestamp).getTime(),
        );
        return all.slice(0, maxSignals);
      });
    };

    // Fetch des derniers signaux selon la fenêtre demandée.
    // sinceHours → /signals (search, jusqu'à 720h / limit 1000) ; sinon
    // /signals/latest (limit max 200, fenêtre temporelle implicite).
    const fetchLatest = (): Promise<Signal[]> =>
      sinceHours
        ? searchSignals(client, {
            entity,
            horizon,
            sinceHours,
            limit: Math.min(preloadLimit, 1000),
          })
        : getLatestSignals(client, {
            entity,
            horizon,
            limit: Math.min(preloadLimit, 200),
          });

    // Catch-up best-effort : un échec ne casse pas l'UI (les signaux déjà
    // affichés restent, on retentera au prochain événement).
    const resync = async () => {
      try {
        const latest = await fetchLatest();
        if (cancelled) return;
        mergeInto(latest);
      } catch {
        // best-effort
      }
    };
    // Expose le resync courant au callback `refresh` stable (pull-to-refresh).
    resyncRef.current = resync;

    if (!apiKey) {
      setSignals([]);
      setConnectionState('idle');
      return;
    }

    // Preload initial (remplace l'état) avant d'ouvrir la WS.
    setPreloadLoading(true);
    setPreloadError(null);
    void (async () => {
      try {
        const latest = await fetchLatest();
        if (cancelled) return;
        // L'endpoint retourne déjà du plus récent au plus ancien.
        setSignals(latest.slice(0, maxSignals));
      } catch (err) {
        if (cancelled) return;
        setPreloadError((err as Error).message);
      } finally {
        if (!cancelled) setPreloadLoading(false);
      }
    })();

    // Ouvre le stream WS.
    let everConnected = false;
    const stream = new TikStream({
      baseUrl,
      apiKey,
      entity,
      horizon,
    });
    stream.setCallbacks({
      onSignal: addSignal,
      onStateChange: (state) => {
        if (cancelled) return;
        setConnectionState(state);
        if (state !== 'auth_error') setError(null);
        if (state === 'connected') {
          // Reconnexion (pas la 1re connexion, déjà couverte par le preload) :
          // rattrape les signaux émis pendant la coupure.
          if (everConnected) void resync();
          everConnected = true;
        }
      },
      onError: (err) => {
        if (cancelled) return;
        setError(err.message);
      },
    });
    streamRef.current = stream;
    stream.start();

    // Reprise au premier plan (mobile) : iOS gèle la WS quand l'app passe en
    // arrière-plan / écran éteint, et les signaux émis pendant ce gel ne sont
    // jamais poussés. Au retour :
    //   1. rattrapage REST systématique (peu coûteux, comble le trou même si
    //      le socket paraît encore "connected" = cas zombie iOS) ;
    //   2. si la WS n'est pas saine, on force une reconnexion immédiate plutôt
    //      que d'attendre le backoff (jusqu'à 60 s).
    const onAppStateChange = (next: AppStateStatus) => {
      if (cancelled || next !== 'active') return;
      void resync();
      if (stream.connectionState !== 'connected') {
        stream.forceReconnect();
      }
    };
    const appStateSub = AppState.addEventListener('change', onAppStateChange);

    return () => {
      cancelled = true;
      appStateSub.remove();
      stream.stop();
      streamRef.current = null;
    };
  }, [client, baseUrl, apiKey, entity, horizon, maxSignals, preloadLimit, sinceHours]);

  // Stable shape pour éviter des re-renders inutiles côté consumer.
  return useMemo(
    () => ({
      signals,
      connectionState,
      error,
      preloadLoading,
      preloadError,
      refresh,
    }),
    [signals, connectionState, error, preloadLoading, preloadError, refresh],
  );
}
