/**
 * useSignalFreshness — détecte une panne silencieuse de production de signaux.
 *
 * Poll l'endpoint /metrics/signal_freshness (défaut 60s). `stale=true` quand
 * aucun signal n'a été produit depuis threshold_seconds (défaut 60 min côté
 * core). Le composant SignalFreshnessBanner affiche alors un bandeau rouge.
 *
 * M4 (audit 2026-05-24). Flag d'annulation LOCAL au cycle d'effet (pas de
 * cancelledRef partagé — évite la ré-entrance entre cycles, cf. audit dashboard).
 */

import { useEffect, useState } from 'react';

import { getSignalFreshness } from '@/src/api/endpoints';
import { SignalFreshness } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const REFRESH_INTERVAL_MS = 60_000;

export interface UseSignalFreshnessResult {
  freshness: SignalFreshness | null;
  loading: boolean;
}

export function useSignalFreshness(
  refreshIntervalMs = REFRESH_INTERVAL_MS,
): UseSignalFreshnessResult {
  const { client, apiKey } = useAuth();
  const [freshness, setFreshness] = useState<SignalFreshness | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    if (!apiKey) {
      setFreshness(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    const run = async () => {
      try {
        const fr = await getSignalFreshness(client);
        if (!cancelled) setFreshness(fr);
      } catch {
        // Best-effort : si la mesure échoue (core injoignable, réseau), on
        // n'affiche PAS de bannière "stale" basée sur une mesure manquante —
        // le cas "core down" est couvert par l'indicateur d'état du core
        // (onglet Système). Évite un faux positif alarmant.
        if (!cancelled) setFreshness(null);
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

  return { freshness, loading };
}
