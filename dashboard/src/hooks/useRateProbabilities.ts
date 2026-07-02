/**
 * useRateProbabilities — probabilités de taux Fed par réunion FOMC (ADR-029).
 *
 * Reproduit le « flagship » de centralbank.watch (proba hausse/maintien/baisse)
 * via la maths CME FedWatch côté backend. Pattern aligné sur `useMacroRegime` :
 * fetch initial + poll long (l'ingester tourne toutes les 6 h, futures quotidiens).
 *
 * CONTEXTE STRICT : anticipation du marché (lecture seule), ne génère ni
 * n'influence aucun signal Tik.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getRateProbabilities } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { RateProbabilities } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

import { useAppForeground } from './use-app-foreground';

const REFRESH_INTERVAL_MS = 15 * 60_000; // 15 min — futures lents

export interface UseRateProbabilitiesResult {
  rates: RateProbabilities | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useRateProbabilities(
  refreshIntervalMs: number = REFRESH_INTERVAL_MS,
): UseRateProbabilitiesResult {
  const { client, apiKey } = useAuth();
  const [rates, setRates] = useState<RateProbabilities | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const data = await getRateProbabilities(client);
      if (cancelledRef.current) return;
      setRates(data);
      setError(null);
    } catch (err) {
      if (cancelledRef.current) return;
      const msg = err instanceof TikError ? err.message : (err as Error).message;
      setError(msg);
    }
  }, [client, apiKey]);

  useEffect(() => {
    cancelledRef.current = false;
    if (!apiKey) {
      setLoading(false);
      return;
    }

    setLoading(true);
    void (async () => {
      await refresh();
      if (!cancelledRef.current) setLoading(false);
    })();

    const id = setInterval(() => {
      void refresh();
    }, refreshIntervalMs);

    return () => {
      cancelledRef.current = true;
      clearInterval(id);
    };
  }, [refresh, apiKey, refreshIntervalMs]);

  useAppForeground(refresh);

  return { rates, loading, error, refresh };
}
