/**
 * useTradingView — récupère les recommandations techniques TradingView :
 * panier MACRO (DXY/SPX/US10Y/Or/VIX en 1D) + MICRO par actif (BTC et GOLD en
 * 5m/15m/1h). MODE SHADOW — analyse technique de contexte, PAS un signal Tik
 * (ADR-031 : ne touche jamais direction/veracity).
 *
 * Pattern aligné sur `useDerivatives` : fetch initial + poll régulier. L'ingester
 * publie toutes les 30 min → poll 2 min suffit largement.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getTradingViewMacro, getTradingViewMicro } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { TradingViewSnapshot } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const REFRESH_INTERVAL_MS = 120_000;

export interface UseTradingViewResult {
  macro: TradingViewSnapshot | null;
  microBtc: TradingViewSnapshot | null;
  microGold: TradingViewSnapshot | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useTradingView(
  options: { refreshIntervalMs?: number } = {},
): UseTradingViewResult {
  const { client, apiKey } = useAuth();
  const refreshIntervalMs = options.refreshIntervalMs ?? REFRESH_INTERVAL_MS;

  const [macro, setMacro] = useState<TradingViewSnapshot | null>(null);
  const [microBtc, setMicroBtc] = useState<TradingViewSnapshot | null>(null);
  const [microGold, setMicroGold] = useState<TradingViewSnapshot | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const [m, btc, gold] = await Promise.all([
        getTradingViewMacro(client),
        getTradingViewMicro(client, 'BTC'),
        getTradingViewMicro(client, 'GOLD'),
      ]);
      if (cancelledRef.current) return;
      setMacro(m);
      setMicroBtc(btc);
      setMicroGold(gold);
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

    setMacro(null);
    setMicroBtc(null);
    setMicroGold(null);
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

  return { macro, microBtc, microGold, loading, error, refresh };
}
