/**
 * useUpcomingMacroEvents — récupère les events macro programmés (FOMC, NFP, CPI…).
 *
 * Lacune B Phase B1 J+10 (cf. ADR-017). Pattern aligné sur `useTopHeadlines` :
 * fetch initial + poll à intervalle régulier. Refresh long (5 min) car les
 * events macro changent une fois par jour au plus (cycle ingester FRED Calendar
 * daily). Cohérent avec le TTL cache Redis 5 min côté endpoint.
 *
 * Pattern OSINT pro : on affiche les dates programmées et l'importance,
 * l'humain anticipe ses positions. Zéro signal trading généré.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { getUpcomingMacroEvents, MacroEventsParams } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { MacroEvent } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const REFRESH_INTERVAL_MS = 5 * 60_000; // 5 min — cohérent TTL cache Redis

export interface UseUpcomingMacroEventsResult {
  events: MacroEvent[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

interface UseUpcomingMacroEventsOptions extends MacroEventsParams {
  refreshIntervalMs?: number;
}

export function useUpcomingMacroEvents(
  options: UseUpcomingMacroEventsOptions = {},
): UseUpcomingMacroEventsResult {
  const { client, apiKey } = useAuth();
  const refreshIntervalMs = options.refreshIntervalMs ?? REFRESH_INTERVAL_MS;
  const hours = options.hours ?? 168;
  const importance = options.importance;
  const entityId = options.entityId;
  const limit = options.limit ?? 50;

  const [events, setEvents] = useState<MacroEvent[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    try {
      const data = await getUpcomingMacroEvents(client, {
        hours,
        importance,
        entityId,
        limit,
      });
      if (cancelledRef.current) return;
      setEvents(data);
      setError(null);
    } catch (err) {
      if (cancelledRef.current) return;
      const msg = err instanceof TikError ? err.message : (err as Error).message;
      setError(msg);
    }
  }, [client, apiKey, hours, importance, entityId, limit]);

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

  return { events, loading, error, refresh };
}
