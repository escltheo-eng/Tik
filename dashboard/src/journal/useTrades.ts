/**
 * useTrades — état du carnet de trades manuels (Levier B 2026-06-03).
 *
 * Source serveur (choix trader : stockage VPS, pas AsyncStorage). Charge la
 * liste + le bilan agrégé, et expose des mutations (ouvrir / clôturer /
 * supprimer) qui rafraîchissent l'ensemble derrière elles.
 *
 * Pattern fetch identique au reste du dashboard (useEffect + endpoints +
 * client de `useAuth`). Pas de cache : volume faible (trades manuels), la
 * fraîcheur prime.
 */

import { useCallback, useEffect, useState } from 'react';

import {
  closeTrade,
  deleteTrade,
  getTradeStats,
  listTrades,
  openTrade,
} from '@/src/api/endpoints';
import type {
  ManualTrade,
  ManualTradeCloseInput,
  ManualTradeInput,
  ManualTradeStats,
} from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

export interface UseTradesResult {
  trades: ManualTrade[];
  stats: ManualTradeStats | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  open: (payload: ManualTradeInput) => Promise<ManualTrade>;
  close: (tradeId: string, payload: ManualTradeCloseInput) => Promise<void>;
  remove: (tradeId: string) => Promise<void>;
}

export function useTrades(): UseTradesResult {
  const { client, isAuthenticated } = useAuth();
  const [trades, setTrades] = useState<ManualTrade[]>([]);
  const [stats, setStats] = useState<ManualTradeStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!isAuthenticated) {
      setTrades([]);
      setStats(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [list, st] = await Promise.all([
        listTrades(client, { limit: 200 }),
        getTradeStats(client),
      ]);
      setTrades(list);
      setStats(st);
    } catch (err) {
      setError((err as Error).message ?? 'erreur');
    } finally {
      setLoading(false);
    }
  }, [client, isAuthenticated]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const open = useCallback(
    async (payload: ManualTradeInput) => {
      const created = await openTrade(client, payload);
      await refresh();
      return created;
    },
    [client, refresh],
  );

  const close = useCallback(
    async (tradeId: string, payload: ManualTradeCloseInput) => {
      await closeTrade(client, tradeId, payload);
      await refresh();
    },
    [client, refresh],
  );

  const remove = useCallback(
    async (tradeId: string) => {
      await deleteTrade(client, tradeId);
      await refresh();
    },
    [client, refresh],
  );

  return { trades, stats, loading, error, refresh, open, close, remove };
}
