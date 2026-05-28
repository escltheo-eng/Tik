/**
 * usePolymarket — récupère le snapshot Polymarket (cotes des marchés
 * prédictifs) pour une entity (BTC/GOLD). MODE SHADOW — contexte de marché.
 *
 * Pattern aligné sur `useTopHeadlines` : fetch initial + poll régulier, reset
 * complet quand l'entity change. Les cotes bougent lentement (ingester horaire)
 * → poll 2 min suffit.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getPolymarketMarkets, PolymarketParams } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { PolymarketSnapshot } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const REFRESH_INTERVAL_MS = 120_000;

export interface UsePolymarketResult {
  snapshot: PolymarketSnapshot | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

interface UsePolymarketOptions extends PolymarketParams {
  refreshIntervalMs?: number;
}

export function usePolymarket(
  entityId: string,
  options: UsePolymarketOptions = {},
): UsePolymarketResult {
  const { client, apiKey } = useAuth();
  const refreshIntervalMs = options.refreshIntervalMs ?? REFRESH_INTERVAL_MS;
  const limit = options.limit ?? 10;

  const [snapshot, setSnapshot] = useState<PolymarketSnapshot | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const data = await getPolymarketMarkets(client, entityId, { limit });
      if (cancelledRef.current) return;
      setSnapshot(data);
      setError(null);
    } catch (err) {
      if (cancelledRef.current) return;
      const msg = err instanceof TikError ? err.message : (err as Error).message;
      setError(msg);
    }
  }, [client, apiKey, entityId, limit]);

  useEffect(() => {
    cancelledRef.current = false;
    if (!apiKey) {
      setLoading(false);
      return;
    }

    // Reset quand l'entity change (évite d'afficher du BTC pendant le fetch GOLD).
    setSnapshot(null);
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
  }, [refresh, apiKey, refreshIntervalMs, entityId]);

  return { snapshot, loading, error, refresh };
}
