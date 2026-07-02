/**
 * useTopHeadlines — récupère les derniers titres bruts OSINT pour une entity.
 *
 * Pattern aligné sur `useDashboardKpis` : fetch initial + poll à intervalle
 * régulier (défaut 60s). Réinitialise complètement la liste quand l'entity
 * change (BTC ↔ GOLD).
 *
 * Phase 1 trading manuel J+10 — pattern OSINT pro : on affiche les titres
 * bruts, l'humain interprète. Zéro hallucination LLM.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getTopHeadlines, TopHeadlinesParams } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { Headline } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

import { useAppForeground } from './use-app-foreground';

const REFRESH_INTERVAL_MS = 60_000;

export interface UseTopHeadlinesResult {
  headlines: Headline[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

interface UseTopHeadlinesOptions extends TopHeadlinesParams {
  refreshIntervalMs?: number;
}

export function useTopHeadlines(
  entityId: string,
  options: UseTopHeadlinesOptions = {},
): UseTopHeadlinesResult {
  const { client, apiKey } = useAuth();
  const refreshIntervalMs = options.refreshIntervalMs ?? REFRESH_INTERVAL_MS;
  const limit = options.limit ?? 10;
  const sinceHours = options.sinceHours ?? 24;
  const sort = options.sort ?? 'credibility_recency';

  const [headlines, setHeadlines] = useState<Headline[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const data = await getTopHeadlines(client, entityId, {
        limit,
        sinceHours,
        sort,
      });
      if (cancelledRef.current) return;
      setHeadlines(data);
      setError(null);
    } catch (err) {
      if (cancelledRef.current) return;
      const msg = err instanceof TikError ? err.message : (err as Error).message;
      setError(msg);
    }
  }, [client, apiKey, entityId, limit, sinceHours, sort]);

  useEffect(() => {
    cancelledRef.current = false;
    if (!apiKey) {
      setLoading(false);
      return;
    }

    // Reset complet quand l'entity change (évite d'afficher des titres
    // BTC pendant le fetch GOLD).
    setHeadlines([]);
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

  useAppForeground(refresh);

  return { headlines, loading, error, refresh };
}
