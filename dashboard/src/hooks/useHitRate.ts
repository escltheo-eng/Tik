/**
 * useHitRate — récupère le hit rate live des signaux Tik pour une combinaison
 * entity × horizon, avec polling régulier.
 *
 * Phase A.2 trading manuel J+10 — calibration empirique de la confiance avant
 * de prendre une décision réelle. Réutilise la logique du backtest CLI via
 * l'endpoint `/api/v1/metrics/hit_rate` (cache Redis TTL 15 min côté serveur).
 *
 * Pattern aligné sur `useTopHeadlines` : fetch initial + poll à intervalle
 * régulier (défaut 60s). Reset complet quand entity ou horizon change.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getHitRate, HitRateParams } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { HitRate } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

import { useAppForeground } from './use-app-foreground';

const REFRESH_INTERVAL_MS = 60_000;

export interface UseHitRateResult {
  data: HitRate | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

interface UseHitRateOptions extends HitRateParams {
  refreshIntervalMs?: number;
}

export function useHitRate(
  entityId: string,
  horizon: string,
  options: UseHitRateOptions = {},
): UseHitRateResult {
  const { client, apiKey } = useAuth();
  const refreshIntervalMs = options.refreshIntervalMs ?? REFRESH_INTERVAL_MS;
  const sinceDays = options.sinceDays ?? 30;
  const includeFlagged = options.includeFlagged ?? false;
  const thresholdPct = options.thresholdPct;

  const [data, setData] = useState<HitRate | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const result = await getHitRate(client, entityId, horizon, {
        sinceDays,
        thresholdPct,
        includeFlagged,
      });
      if (cancelledRef.current) return;
      setData(result);
      setError(null);
    } catch (err) {
      if (cancelledRef.current) return;
      const msg = err instanceof TikError ? err.message : (err as Error).message;
      setError(msg);
    }
  }, [client, apiKey, entityId, horizon, sinceDays, thresholdPct, includeFlagged]);

  useEffect(() => {
    cancelledRef.current = false;
    if (!apiKey) {
      setLoading(false);
      return;
    }

    setData(null);
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
  }, [refresh, apiKey, refreshIntervalMs, entityId, horizon, includeFlagged]);

  useAppForeground(refresh);

  return { data, loading, error, refresh };
}
