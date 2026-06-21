/**
 * useStablecoins — récupère la masse de stablecoins + tendance (ADR-031).
 *
 * « Poudre sèche » crypto-native (DefiLlama, gratuit) calculée côté backend.
 * Pattern aligné sur `useMacroRegime` : fetch initial + poll long (l'ingester
 * tourne toutes les 6 h, données quotidiennes → 15 min suffit) + refresh au retour
 * au premier plan.
 *
 * CONTEXTE STRICT : ces chiffres ne sont QUE du contexte (lecture seule), ils ne
 * génèrent ni n'influencent aucun signal Tik.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getStablecoins } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { Stablecoins } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

import { useAppForeground } from './use-app-foreground';

const REFRESH_INTERVAL_MS = 15 * 60_000; // 15 min — données quotidiennes lentes

export interface UseStablecoinsResult {
  stablecoins: Stablecoins | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useStablecoins(refreshIntervalMs: number = REFRESH_INTERVAL_MS): UseStablecoinsResult {
  const { client, apiKey } = useAuth();
  const [stablecoins, setStablecoins] = useState<Stablecoins | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const data = await getStablecoins(client);
      if (cancelledRef.current) return;
      setStablecoins(data);
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

  return { stablecoins, loading, error, refresh };
}
