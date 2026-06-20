/**
 * useBreakingNews — derniers titres breaking-news captés (ADR-027).
 *
 * Poll l'endpoint /metrics/breaking_news (défaut 60s). Renvoie les titres
 * géopol/macro à fort impact captés par le BreakingNewsIngester (les mêmes que
 * ceux qui déclenchent l'alerte Telegram), plus récents en tête.
 *
 * ⚠️ Alerting / contexte / discipline — PAS un signal directionnel (ne touche
 * jamais le combined_bias ni la véracité). Best-effort : si la mesure échoue
 * (core injoignable), on renvoie une liste vide plutôt qu'une fausse erreur.
 */

import { useEffect, useState } from 'react';
import { AppState } from 'react-native';

import { getBreakingNews, getBreakingReactions } from '@/src/api/endpoints';
import { BreakingNewsItem, BreakingReaction } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const REFRESH_INTERVAL_MS = 60_000;

export interface UseBreakingNewsResult {
  items: BreakingNewsItem[];
  reactions: BreakingReaction[];
  loading: boolean;
}

export function useBreakingNews(
  limit = 20,
  refreshIntervalMs = REFRESH_INTERVAL_MS,
): UseBreakingNewsResult {
  const { client, apiKey } = useAuth();
  const [items, setItems] = useState<BreakingNewsItem[]>([]);
  const [reactions, setReactions] = useState<BreakingReaction[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    if (!apiKey) {
      setItems([]);
      setReactions([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    const run = async () => {
      // Best-effort indépendant : un échec sur l'un ne casse pas l'autre.
      try {
        const data = await getBreakingNews(client, { limit });
        if (!cancelled) setItems(data);
      } catch {
        if (!cancelled) setItems([]);
      }
      try {
        const rx = await getBreakingReactions(client, { limit: 6 });
        if (!cancelled) setReactions(rx);
      } catch {
        if (!cancelled) setReactions([]);
      }
      if (!cancelled) setLoading(false);
    };
    void run();
    const id = setInterval(() => void run(), refreshIntervalMs);
    // Retour au premier plan : l'OS gèle setInterval en arrière-plan → refetch immédiat.
    const fgSub = AppState.addEventListener('change', (next) => {
      if (next === 'active') void run();
    });
    return () => {
      cancelled = true;
      clearInterval(id);
      fgSub.remove();
    };
  }, [client, apiKey, limit, refreshIntervalMs]);

  return { items, reactions, loading };
}
