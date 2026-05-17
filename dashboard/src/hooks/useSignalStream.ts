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

import { useEffect, useMemo, useRef, useState } from 'react';

import { getLatestSignals, searchSignals } from '@/src/api/endpoints';
import { ConnectionState, TikStream } from '@/src/api/stream';
import { Signal } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

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

  useEffect(() => {
    let cancelled = false;

    const addSignal = (incoming: Signal) => {
      if (cancelled) return;
      setSignals((prev) => {
        // Si on a déjà ce signal (par id), on remplace pour préserver l'ordre.
        const filtered = prev.filter((s) => s.id !== incoming.id);
        const merged = [incoming, ...filtered];
        return merged.slice(0, maxSignals);
      });
    };

    if (!apiKey) {
      setSignals([]);
      setConnectionState('idle');
      return;
    }

    // Précharge les derniers signaux via REST avant d'ouvrir la WS.
    // Si sinceHours est fourni, on utilise /signals (search) qui supporte
    // jusqu'à 720h et limit 1000. Sinon /signals/latest (limit max 200,
    // fenêtre temporelle implicite).
    setPreloadLoading(true);
    setPreloadError(null);
    void (async () => {
      try {
        const latest = sinceHours
          ? await searchSignals(client, {
              entity,
              horizon,
              sinceHours,
              limit: Math.min(preloadLimit, 1000),
            })
          : await getLatestSignals(client, {
              entity,
              horizon,
              limit: Math.min(preloadLimit, 200),
            });
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
      },
      onError: (err) => {
        if (cancelled) return;
        setError(err.message);
      },
    });
    streamRef.current = stream;
    stream.start();

    return () => {
      cancelled = true;
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
    }),
    [signals, connectionState, error, preloadLoading, preloadError],
  );
}
