/**
 * useMacroReading — récupère les lectures macro (mécanisme éducatif + réaction
 * mesurée BTC/OR). Données quasi statiques côté backend (cache 24h) → poll lent.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getMacroReading } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { MacroReading } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const REFRESH_INTERVAL_MS = 30 * 60_000; // 30 min (backend caché 24h)

export interface UseMacroReadingResult {
  readings: MacroReading[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useMacroReading(): UseMacroReadingResult {
  const { client, apiKey } = useAuth();
  const [readings, setReadings] = useState<MacroReading[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const data = await getMacroReading(client);
      if (cancelledRef.current) return;
      setReadings(data);
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
    void (async () => {
      await refresh();
      if (!cancelledRef.current) setLoading(false);
    })();
    const id = setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    return () => {
      cancelledRef.current = true;
      clearInterval(id);
    };
  }, [refresh, apiKey]);

  return { readings, loading, error, refresh };
}
