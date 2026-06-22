/**
 * useCrossAsset — récupère les corrélations cross-asset du BTC (ADR-032).
 *
 * Avec quoi le BTC co-bouge (actions/or/dollar), calculé côté backend depuis Yahoo.
 * Pattern aligné sur `useMacroRegime` : fetch initial + poll long (l'ingester tourne
 * toutes les 6 h, cours quotidiens) + refresh au retour au premier plan.
 *
 * CONTEXTE STRICT : ces chiffres ne sont QUE du contexte (lecture seule), ils ne
 * génèrent ni n'influencent aucun signal Tik. Une corrélation n'est pas une prédiction.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getCrossAsset } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { CrossAsset } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

import { useAppForeground } from './use-app-foreground';

const REFRESH_INTERVAL_MS = 15 * 60_000; // 15 min — cours quotidiens lents

export interface UseCrossAssetResult {
  crossAsset: CrossAsset | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useCrossAsset(refreshIntervalMs: number = REFRESH_INTERVAL_MS): UseCrossAssetResult {
  const { client, apiKey } = useAuth();
  const [crossAsset, setCrossAsset] = useState<CrossAsset | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const data = await getCrossAsset(client);
      if (cancelledRef.current) return;
      setCrossAsset(data);
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

  return { crossAsset, loading, error, refresh };
}
