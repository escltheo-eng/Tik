/**
 * useMacroRegime — récupère le régime macro objectif (ADR-028).
 *
 * Fed Net Liquidity + taux réel 10Y + proba récession + pente courbe +
 * conditions financières, calculés depuis FRED (gratuit) côté backend. Pattern
 * aligné sur `useUpcomingMacroEvents` : fetch initial + poll long (l'ingester
 * tourne toutes les 6 h, données hebdo/quotidiennes → 15 min suffit largement).
 *
 * CONTEXTE STRICT : ces chiffres ne sont QUE du contexte (lecture seule), ils ne
 * génèrent ni n'influencent aucun signal Tik.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getMacroRegime } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { MacroRegime } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const REFRESH_INTERVAL_MS = 15 * 60_000; // 15 min — données macro lentes (hebdo/quotid)

export interface UseMacroRegimeResult {
  regime: MacroRegime | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useMacroRegime(refreshIntervalMs: number = REFRESH_INTERVAL_MS): UseMacroRegimeResult {
  const { client, apiKey } = useAuth();
  const [regime, setRegime] = useState<MacroRegime | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const data = await getMacroRegime(client);
      if (cancelledRef.current) return;
      setRegime(data);
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

  return { regime, loading, error, refresh };
}
