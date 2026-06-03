/**
 * useDerivatives — récupère le snapshot positionnement dérivés Binance (funding,
 * open interest, ratios long/short retail + top traders) pour une entity (BTC).
 * MODE SHADOW — contexte de marché, PAS un signal Tik (ADR-023).
 *
 * Pattern aligné sur `usePolymarket` : fetch initial + poll régulier. L'ingester
 * publie toutes les heures → poll 2 min suffit largement.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getDerivatives } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { DerivativesSnapshot } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const REFRESH_INTERVAL_MS = 120_000;

export interface UseDerivativesResult {
  snapshot: DerivativesSnapshot | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useDerivatives(
  entityId: string = 'BTC',
  options: { refreshIntervalMs?: number } = {},
): UseDerivativesResult {
  const { client, apiKey } = useAuth();
  const refreshIntervalMs = options.refreshIntervalMs ?? REFRESH_INTERVAL_MS;

  const [snapshot, setSnapshot] = useState<DerivativesSnapshot | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const data = await getDerivatives(client, entityId);
      if (cancelledRef.current) return;
      setSnapshot(data);
      setError(null);
    } catch (err) {
      if (cancelledRef.current) return;
      const msg = err instanceof TikError ? err.message : (err as Error).message;
      setError(msg);
    }
  }, [client, apiKey, entityId]);

  useEffect(() => {
    cancelledRef.current = false;
    if (!apiKey) {
      setLoading(false);
      return;
    }

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
