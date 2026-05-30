/**
 * useMacroReadingLive — bandeau « ticker » macro qui se cale sur le calendrier
 * réel : prochain event programmé + dernier event passé dans la fenêtre récente
 * (±48h) avec le mouvement % BTC/OR depuis l'annonce.
 *
 * Backend cache 3 min → poll 3 min côté front (aligné, pas de gaspillage).
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getMacroReadingLive } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { MacroLiveOut } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const REFRESH_INTERVAL_MS = 3 * 60_000; // 3 min (aligné backend LIVE_CACHE_TTL_S)

export interface UseMacroReadingLiveResult {
  live: MacroLiveOut | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useMacroReadingLive(): UseMacroReadingLiveResult {
  const { client, apiKey } = useAuth();
  const [live, setLive] = useState<MacroLiveOut | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const data = await getMacroReadingLive(client);
      if (cancelledRef.current) return;
      setLive(data);
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

  return { live, loading, error, refresh };
}
