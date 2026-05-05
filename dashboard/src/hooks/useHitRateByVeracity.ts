/**
 * useHitRateByVeracity — récupère le hit rate segmenté par tranche de veracity.
 *
 * Phase A.2-bis trading manuel J+10. Insight critique du backtest 2026-05-05 :
 * le hit rate global brut est trompeur (24% sur 156 signaux 5j), alors que
 * filtré sur veracity ≥ 0.90 il monte à 42-67%. Cette mesure rend le filtre
 * exploitable côté UI.
 *
 * Pattern aligné sur useHitRate. Mêmes paramètres (entity, horizon, since_days,
 * include_flagged) → résultats synchronisés visuellement.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getHitRateByVeracity, HitRateParams } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { HitRateByVeracity } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const REFRESH_INTERVAL_MS = 60_000;

export interface UseHitRateByVeracityResult {
  data: HitRateByVeracity | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

interface UseHitRateByVeracityOptions extends HitRateParams {
  refreshIntervalMs?: number;
}

export function useHitRateByVeracity(
  entityId: string,
  horizon: string,
  options: UseHitRateByVeracityOptions = {},
): UseHitRateByVeracityResult {
  const { client, apiKey } = useAuth();
  const refreshIntervalMs = options.refreshIntervalMs ?? REFRESH_INTERVAL_MS;
  const sinceDays = options.sinceDays ?? 30;
  const includeFlagged = options.includeFlagged ?? false;
  const thresholdPct = options.thresholdPct;

  const [data, setData] = useState<HitRateByVeracity | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const result = await getHitRateByVeracity(client, entityId, horizon, {
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

  return { data, loading, error, refresh };
}
