/**
 * useSourceHealth — santé par source OSINT (détection de dégradation silencieuse).
 *
 * Poll l'endpoint /metrics/source_health (défaut 60s). Chaque source est classée
 * ok / stale / missing selon la fraîcheur de sa clé Redis. `any_critical_down`
 * signale qu'une source critique (FG, CryptoCompare, Google News BTC, prix BTC)
 * ne publie plus. Complète M4 (qui ne voit que la production agrégée).
 *
 * Best-effort : si la mesure échoue (core injoignable), on renvoie null plutôt
 * qu'un faux "down" (le cas core-down est couvert par l'état du core).
 */

import { useEffect, useState } from 'react';

import { getSourceHealth } from '@/src/api/endpoints';
import { SourceHealth } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const REFRESH_INTERVAL_MS = 60_000;

export interface UseSourceHealthResult {
  health: SourceHealth | null;
  loading: boolean;
}

export function useSourceHealth(
  refreshIntervalMs = REFRESH_INTERVAL_MS,
): UseSourceHealthResult {
  const { client, apiKey } = useAuth();
  const [health, setHealth] = useState<SourceHealth | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    if (!apiKey) {
      setHealth(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    const run = async () => {
      try {
        const h = await getSourceHealth(client);
        if (!cancelled) setHealth(h);
      } catch {
        if (!cancelled) setHealth(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    const id = setInterval(() => void run(), refreshIntervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [client, apiKey, refreshIntervalMs]);

  return { health, loading };
}
