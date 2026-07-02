/**
 * AlertsContext — accumule les événements remarquables du flux WS.
 *
 * Trois types d'alertes (cohérents avec les hooks SDK Python `stream.py`) :
 *   - `crash_warning`        : `signal.advisory.macro_crash_warning === true`
 *   - `fake_news_detected`   : `signal.circuit_breaker_status !== "ok"`
 *   - `veracity_collapse`    : `signal.veracity < threshold` (défaut 0.5)
 *
 * Le provider démarre une seule WebSocket dédiée aux alertes (sans filtre
 * entity/horizon, on veut tout savoir). Quand l'utilisateur n'est pas
 * authentifié, le stream reste fermé.
 *
 * Persistance : les alertes sont stockées dans AsyncStorage (clé
 * `tik.alerts.v1`). Hydratation eager au mount du provider (avant le
 * premier render) ; persistance à chaque changement de la liste. Cap à
 * MAX_ALERTS=50 inchangé. Bug A section 10 CLAUDE.md résolu.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { AppState, type AppStateStatus } from 'react-native';

import { HttpClient } from '@/src/api/client';
import { searchSignals } from '@/src/api/endpoints';
import { TikStream } from '@/src/api/stream';
import { Signal } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';
import { deriveAlertTypes } from '@/src/alerts/derive';
import { parseUtcIso } from '@/src/utils/time';

const MAX_ALERTS = 50;
const VERACITY_COLLAPSE_THRESHOLD = 0.5;
const STORAGE_KEY = 'tik.alerts.v1';
// Fenêtre du rattrapage REST (audit D-2, 2026-07-02) : les alertes émises
// pendant que l'app était fermée/en fond sont re-dérivées des signaux des
// dernières RESYNC_SINCE_HOURS heures (mêmes règles que le flux WS —
// src/alerts/derive.ts). Au-delà, l'historique persisté fait foi.
const RESYNC_SINCE_HOURS = 48;
const RESYNC_LIMIT = 500;

export type AlertType = 'crash_warning' | 'fake_news_detected' | 'veracity_collapse';

export interface AlertEntry {
  id: string;
  type: AlertType;
  signalId: string;
  signalEntity: string;
  signalHorizon: string;
  signalDirection: string;
  signalVeracity: number;
  signalConfidence: number;
  signalTimestamp: string;
  receivedAt: string;
  read: boolean;
}

interface AlertsContextValue {
  alerts: AlertEntry[];
  unreadCount: number;
  connected: boolean;
  markAsRead: (id: string) => void;
  markAllAsRead: () => void;
  clear: () => void;
}

const AlertsContext = createContext<AlertsContextValue | null>(null);

function buildAlert(type: AlertType, signal: Signal, receivedAt?: string): AlertEntry {
  return {
    id: `${signal.id}:${type}`,
    type,
    signalId: signal.id,
    signalEntity: signal.entity_id,
    signalHorizon: signal.horizon,
    signalDirection: signal.direction,
    signalVeracity: signal.veracity,
    signalConfidence: signal.confidence,
    signalTimestamp: signal.timestamp,
    // Rattrapage REST : receivedAt = timestamp du signal (honnête : le moment
    // où l'alerte AURAIT dû arriver), pas le moment du rattrapage.
    receivedAt: receivedAt ?? new Date().toISOString(),
    read: false,
  };
}

export function AlertsProvider({ children }: { children: ReactNode }) {
  const { baseUrl, apiKey, isAuthenticated } = useAuth();
  const [alerts, setAlerts] = useState<AlertEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const streamRef = useRef<TikStream | null>(null);

  // Hydratation eager au mount + persistance à chaque changement.
  // Le flag `hydrated` empêche d'écraser le storage avec [] au boot
  // avant que la lecture initiale ait eu lieu.
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        if (cancelled) return;
        if (raw) {
          const parsed = JSON.parse(raw) as AlertEntry[];
          if (Array.isArray(parsed)) {
            // Audit 2026-07-02 : FUSIONNE l'historique persisté avec les
            // alertes arrivées du WS pendant la lecture asynchrone du storage.
            // L'ancien code ignorait le storage si `current` était non vide,
            // puis l'effet de persistance l'écrasait → perte irréversible des
            // 50 alertes historiques (fenêtre de quelques ms au boot, mais
            // conséquence définitive). Dédup par id, plus récentes d'abord,
            // cap MAX_ALERTS inchangé.
            setAlerts((current) => {
              const seen = new Set(current.map((a) => a.id));
              const merged = [...current, ...parsed.filter((a) => !seen.has(a.id))];
              merged.sort(
                (a, b) => parseUtcIso(b.receivedAt).getTime() - parseUtcIso(a.receivedAt).getTime(),
              );
              return merged.slice(0, MAX_ALERTS);
            });
          }
        }
      } catch (err) {
        console.warn('[AlertsContext] failed to hydrate from storage, resetting', err);
        try {
          await AsyncStorage.removeItem(STORAGE_KEY);
        } catch {
          /* swallow */
        }
      } finally {
        if (!cancelled) setHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(alerts)).catch((err) => {
      console.warn('[AlertsContext] failed to persist alerts to storage', err);
    });
  }, [alerts, hydrated]);

  const pushAlert = useCallback((alert: AlertEntry) => {
    setAlerts((prev) => {
      // Dédupe par id (signal × type) pour ne pas spammer si le core
      // re-pousse le même signal.
      if (prev.some((a) => a.id === alert.id)) return prev;
      const next = [alert, ...prev];
      return next.slice(0, MAX_ALERTS);
    });
  }, []);

  // Rattrapage REST des alertes manquées (audit D-2, 2026-07-02).
  // Le flux WS est gelé quand l'app est en fond (iOS) : toute alerte émise
  // pendant ce temps était PERDUE définitivement (badge « Live » trompeur).
  // On re-dérive les alertes depuis les signaux récents — mêmes règles que le
  // WS (source unique : derive.ts), dédup par id via pushAlert. Best-effort.
  const resyncMissedAlerts = useCallback(async () => {
    if (!isAuthenticated || !apiKey) return;
    try {
      const client = new HttpClient({ baseUrl, apiKey });
      const signals = await searchSignals(client, {
        sinceHours: RESYNC_SINCE_HOURS,
        limit: RESYNC_LIMIT,
      });
      for (const signal of signals) {
        for (const type of deriveAlertTypes(signal, VERACITY_COLLAPSE_THRESHOLD)) {
          pushAlert(buildAlert(type, signal, signal.timestamp));
        }
      }
    } catch (err) {
      // Best-effort : le prochain resync (reconnexion / foreground) retentera.
      console.warn('[AlertsContext] resync failed', err);
    }
  }, [baseUrl, apiKey, isAuthenticated, pushAlert]);

  // Resync au boot (après hydratation, pour fusionner et non écraser) + au
  // retour au premier plan (la WS iOS peut être zombie — on force aussi la
  // reconnexion, pattern useSignalStream).
  useEffect(() => {
    if (!hydrated || !isAuthenticated) return;
    void resyncMissedAlerts();

    const onAppStateChange = (next: AppStateStatus) => {
      if (next === 'active') {
        streamRef.current?.forceReconnect();
        void resyncMissedAlerts();
      }
    };
    const sub = AppState.addEventListener('change', onAppStateChange);
    return () => sub.remove();
  }, [hydrated, isAuthenticated, resyncMissedAlerts]);

  useEffect(() => {
    if (!isAuthenticated || !apiKey) {
      streamRef.current?.stop();
      streamRef.current = null;
      setConnected(false);
      return;
    }

    const stream = new TikStream({
      baseUrl,
      apiKey,
      veracityCollapseThreshold: VERACITY_COLLAPSE_THRESHOLD,
    });
    stream.setCallbacks({
      onCrashWarning: (s) => pushAlert(buildAlert('crash_warning', s)),
      onFakeNewsDetected: (s) => pushAlert(buildAlert('fake_news_detected', s)),
      onVeracityCollapse: (s) => pushAlert(buildAlert('veracity_collapse', s)),
      onStateChange: (state) => {
        setConnected(state === 'connected');
        // Chaque (re)connexion peut suivre un trou : rattraper ce qui a été
        // publié pendant la coupure.
        if (state === 'connected') void resyncMissedAlerts();
      },
    });
    streamRef.current = stream;
    stream.start();

    return () => {
      stream.stop();
      streamRef.current = null;
      setConnected(false);
    };
  }, [baseUrl, apiKey, isAuthenticated, pushAlert, resyncMissedAlerts]);

  const markAsRead = useCallback((id: string) => {
    setAlerts((prev) => prev.map((a) => (a.id === id && !a.read ? { ...a, read: true } : a)));
  }, []);

  const markAllAsRead = useCallback(() => {
    setAlerts((prev) => prev.map((a) => (a.read ? a : { ...a, read: true })));
  }, []);

  const clear = useCallback(() => {
    setAlerts([]);
  }, []);

  const unreadCount = useMemo(() => alerts.reduce((c, a) => c + (a.read ? 0 : 1), 0), [alerts]);

  const value = useMemo<AlertsContextValue>(
    () => ({ alerts, unreadCount, connected, markAsRead, markAllAsRead, clear }),
    [alerts, unreadCount, connected, markAsRead, markAllAsRead, clear],
  );

  return <AlertsContext.Provider value={value}>{children}</AlertsContext.Provider>;
}

export function useAlerts(): AlertsContextValue {
  const ctx = useContext(AlertsContext);
  if (ctx === null) throw new Error('useAlerts must be used inside <AlertsProvider>');
  return ctx;
}
