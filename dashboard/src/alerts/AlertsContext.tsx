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
 * Les alertes vivent en mémoire (max 50). Pour persister entre redémarrages,
 * on pourra ajouter un AsyncStorage plus tard si besoin.
 */

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

import { TikStream } from '@/src/api/stream';
import { Signal } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const MAX_ALERTS = 50;
const VERACITY_COLLAPSE_THRESHOLD = 0.5;

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
  markAllAsRead: () => void;
  clear: () => void;
}

const AlertsContext = createContext<AlertsContextValue | null>(null);

function buildAlert(type: AlertType, signal: Signal): AlertEntry {
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
    receivedAt: new Date().toISOString(),
    read: false,
  };
}

export function AlertsProvider({ children }: { children: ReactNode }) {
  const { baseUrl, apiKey, isAuthenticated } = useAuth();
  const [alerts, setAlerts] = useState<AlertEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const streamRef = useRef<TikStream | null>(null);

  const pushAlert = useCallback((alert: AlertEntry) => {
    setAlerts((prev) => {
      // Dédupe par id (signal × type) pour ne pas spammer si le core
      // re-pousse le même signal.
      if (prev.some((a) => a.id === alert.id)) return prev;
      const next = [alert, ...prev];
      return next.slice(0, MAX_ALERTS);
    });
  }, []);

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
      onStateChange: (state) => setConnected(state === 'connected'),
    });
    streamRef.current = stream;
    stream.start();

    return () => {
      stream.stop();
      streamRef.current = null;
      setConnected(false);
    };
  }, [baseUrl, apiKey, isAuthenticated, pushAlert]);

  const markAllAsRead = useCallback(() => {
    setAlerts((prev) => prev.map((a) => (a.read ? a : { ...a, read: true })));
  }, []);

  const clear = useCallback(() => {
    setAlerts([]);
  }, []);

  const unreadCount = useMemo(() => alerts.reduce((c, a) => c + (a.read ? 0 : 1), 0), [alerts]);

  const value = useMemo<AlertsContextValue>(
    () => ({ alerts, unreadCount, connected, markAllAsRead, clear }),
    [alerts, unreadCount, connected, markAllAsRead, clear],
  );

  return <AlertsContext.Provider value={value}>{children}</AlertsContext.Provider>;
}

export function useAlerts(): AlertsContextValue {
  const ctx = useContext(AlertsContext);
  if (ctx === null) throw new Error('useAlerts must be used inside <AlertsProvider>');
  return ctx;
}
