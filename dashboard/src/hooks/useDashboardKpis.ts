/**
 * useDashboardKpis — agrège les KPIs affichés sur l'écran Home.
 *
 * Fetch + poll à intervalle régulier :
 *   - `/veracity/global` (santé globale du scoring de sources)
 *   - `/signals?since_hours=24` (activité du jour)
 *
 * Dérive côté client :
 *   - compteur par horizon (flash, swing, macro)
 *   - dernier signal connu par entity (BTC, GOLD)
 *   - série de veracities pour la sparkline
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { searchSignals, getGlobalVeracity } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { Signal, VeracityStatus } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';
import { isSignalLlmEnriched } from '@/src/utils/llm';
import { parseUtcIso } from '@/src/utils/time';

const REFRESH_INTERVAL_MS = 60_000;
const DEFAULT_TRACKED_ENTITIES = ['BTC', 'GOLD'] as const;
const HORIZONS = ['flash', 'swing', 'macro'] as const;

export type TrackedHorizon = (typeof HORIZONS)[number];

export interface HorizonCounts {
  flash: number;
  swing: number;
  macro: number;
  other: number;
  total: number;
}

export interface LlmLastSignal {
  timestamp: string;
  isLlmOk: boolean;
}

export interface LlmStats {
  total: number;
  llmOk: number;
  percentOk: number | null;
  lastSignal: LlmLastSignal | null;
}

export interface DashboardKpis {
  veracity: VeracityStatus | null;
  veracityError: string | null;
  signals24h: Signal[];
  signals24hError: string | null;
  loading: boolean;
  signalsByHorizon: HorizonCounts;
  lastSignalByEntity: Record<string, Signal | null>;
  veracitySeries: number[];
  llmStatsToday: LlmStats;
  refresh: () => Promise<void>;
}

interface UseDashboardKpisOptions {
  trackedEntities?: readonly string[];
  refreshIntervalMs?: number;
  windowHours?: number;
}

function emptyCounts(): HorizonCounts {
  return { flash: 0, swing: 0, macro: 0, other: 0, total: 0 };
}

function deriveCounts(signals: Signal[]): HorizonCounts {
  const counts = emptyCounts();
  for (const s of signals) {
    counts.total += 1;
    if (s.horizon === 'flash') counts.flash += 1;
    else if (s.horizon === 'swing') counts.swing += 1;
    else if (s.horizon === 'macro') counts.macro += 1;
    else counts.other += 1;
  }
  return counts;
}

function deriveLastByEntity(
  signals: Signal[],
  trackedEntities: readonly string[],
): Record<string, Signal | null> {
  const result: Record<string, Signal | null> = {};
  for (const entity of trackedEntities) {
    result[entity] = null;
  }
  // signals déjà triés desc par timestamp côté core (latest first).
  for (const s of signals) {
    if (s.entity_id in result && result[s.entity_id] === null) {
      result[s.entity_id] = s;
    }
  }
  return result;
}

function deriveVeracitySeries(signals: Signal[], maxPoints = 12): number[] {
  // Inverse l'ordre : du plus ancien au plus récent pour le tracé.
  const sliced = signals.slice(0, maxPoints).reverse();
  return sliced.map((s) => s.veracity);
}

function startOfTodayUtc(now: Date): Date {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

export function deriveLlmStats(signals: Signal[], now: Date): LlmStats {
  const startUtcMs = startOfTodayUtc(now).getTime();
  const todaySignals = signals.filter(
    (s) => parseUtcIso(s.timestamp).getTime() >= startUtcMs,
  );
  const total = todaySignals.length;
  if (total === 0) {
    return { total: 0, llmOk: 0, percentOk: null, lastSignal: null };
  }
  const llmOk = todaySignals.filter(isSignalLlmEnriched).length;
  const percentOk = (llmOk / total) * 100;
  // signals déjà triés desc par timestamp côté core (latest first).
  const latest = todaySignals[0];
  return {
    total,
    llmOk,
    percentOk,
    lastSignal: {
      timestamp: latest.timestamp,
      isLlmOk: isSignalLlmEnriched(latest),
    },
  };
}

export function useDashboardKpis(options: UseDashboardKpisOptions = {}): DashboardKpis {
  const { client, apiKey } = useAuth();
  const trackedEntities = options.trackedEntities ?? DEFAULT_TRACKED_ENTITIES;
  const refreshIntervalMs = options.refreshIntervalMs ?? REFRESH_INTERVAL_MS;
  const windowHours = options.windowHours ?? 24;

  const [veracity, setVeracity] = useState<VeracityStatus | null>(null);
  const [veracityError, setVeracityError] = useState<string | null>(null);
  const [signals24h, setSignals24h] = useState<Signal[]>([]);
  const [signals24hError, setSignals24hError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!apiKey) return;
    const promises: [Promise<VeracityStatus | null>, Promise<Signal[] | null>] = [
      getGlobalVeracity(client).catch((err: unknown) => {
        if (cancelledRef.current) return null;
        const msg = err instanceof TikError ? err.message : (err as Error).message;
        setVeracityError(msg);
        return null;
      }),
      searchSignals(client, { sinceHours: windowHours, limit: 100 }).catch((err: unknown) => {
        if (cancelledRef.current) return null;
        const msg = err instanceof TikError ? err.message : (err as Error).message;
        setSignals24hError(msg);
        return null;
      }),
    ];

    const [vRes, sRes] = await Promise.all(promises);
    if (cancelledRef.current) return;
    if (vRes !== null) {
      setVeracity(vRes);
      setVeracityError(null);
    }
    if (sRes !== null) {
      setSignals24h(sRes);
      setSignals24hError(null);
    }
  }, [client, apiKey, windowHours]);

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

  const signalsByHorizon = useMemo(() => deriveCounts(signals24h), [signals24h]);
  const lastSignalByEntity = useMemo(
    () => deriveLastByEntity(signals24h, trackedEntities),
    [signals24h, trackedEntities],
  );
  const veracitySeries = useMemo(() => deriveVeracitySeries(signals24h, 12), [signals24h]);
  const llmStatsToday = useMemo(() => deriveLlmStats(signals24h, new Date()), [signals24h]);

  return {
    veracity,
    veracityError,
    signals24h,
    signals24hError,
    loading,
    signalsByHorizon,
    lastSignalByEntity,
    veracitySeries,
    llmStatsToday,
    refresh,
  };
}
