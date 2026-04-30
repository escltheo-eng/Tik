/**
 * TikStream — client WebSocket avec reconnexion auto et callbacks d'événements.
 *
 * Miroir simplifié de `sdk/stream.py` côté Python. Utilise l'API WebSocket
 * native (disponible en React Native et en web), donc aucune dépendance
 * externe ajoutée.
 *
 * Comportement :
 *   - Connecte à `/api/v1/ws/signals?api_key=...&entity=...&horizon=...`
 *   - Parse chaque message, ignore les heartbeats côté callback.
 *   - En cas de déconnexion : reconnecte avec backoff exponentiel + jitter.
 *   - Reset du backoff à chaque connexion réussie.
 *
 * Détection auth refusée : le core renvoie code WS 1008 (POLICY_VIOLATION)
 * sur clé API invalide → on stoppe le stream sans retry.
 *
 * ADR-003 — Stream strictement read-only. Aucun message n'est envoyé du
 * dashboard vers le core via WS.
 */

import {
  Signal,
} from './types';
import { INITIAL_BACKOFF_S, buildWsUrl, maskApiKeyInUrl, nextBackoff } from './ws';

export const DEFAULT_VERACITY_COLLAPSE_THRESHOLD = 0.5;
const WS_AUTH_REFUSED_CODE = 1008;
const NORMAL_CLOSURE_CODES = new Set<number>([1000, 1001]);

export type ConnectionState = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'stopped' | 'auth_error';

export interface StreamCallbacks {
  onSignal?: (signal: Signal) => void;
  onCrashWarning?: (signal: Signal) => void;
  onFakeNewsDetected?: (signal: Signal) => void;
  onVeracityCollapse?: (signal: Signal) => void;
  onStateChange?: (state: ConnectionState) => void;
  onError?: (error: Error) => void;
}

export interface TikStreamOptions {
  baseUrl: string;
  apiKey: string;
  entity?: string;
  horizon?: string;
  veracityCollapseThreshold?: number;
}

export class TikStream {
  private readonly url: string;
  private readonly veracityCollapseThreshold: number;
  private callbacks: StreamCallbacks = {};
  private ws: WebSocket | null = null;
  private state: ConnectionState = 'idle';
  private stopped = false;
  private backoff: number = INITIAL_BACKOFF_S;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(opts: TikStreamOptions) {
    this.url = buildWsUrl(opts.baseUrl, {
      apiKey: opts.apiKey,
      entity: opts.entity,
      horizon: opts.horizon,
    });
    this.veracityCollapseThreshold = opts.veracityCollapseThreshold ?? DEFAULT_VERACITY_COLLAPSE_THRESHOLD;
  }

  setCallbacks(callbacks: StreamCallbacks): void {
    this.callbacks = callbacks;
  }

  get connectionState(): ConnectionState {
    return this.state;
  }

  get safeUrl(): string {
    return maskApiKeyInUrl(this.url);
  }

  start(): void {
    if (this.stopped) {
      this.stopped = false;
    }
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.setState('stopped');
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws !== null) {
      try {
        this.ws.close(1000, 'client stop');
      } catch {
        // ignore
      }
      this.ws = null;
    }
  }

  private connect(): void {
    if (this.stopped) return;
    this.setState(this.backoff === INITIAL_BACKOFF_S ? 'connecting' : 'reconnecting');

    let socket: WebSocket;
    try {
      socket = new WebSocket(this.url);
    } catch (err) {
      this.handleError(err as Error);
      this.scheduleReconnect();
      return;
    }
    this.ws = socket;

    socket.onopen = () => {
      this.backoff = INITIAL_BACKOFF_S;
      this.setState('connected');
    };

    socket.onmessage = (event: MessageEvent) => {
      this.processMessage(event.data);
    };

    socket.onerror = () => {
      // L'objet event ne contient pas de détail utilisable cross-platform.
      // On laisse le onclose qui suit gérer la reconnexion.
    };

    socket.onclose = (event: CloseEvent) => {
      this.ws = null;
      if (this.stopped) return;
      if (event.code === WS_AUTH_REFUSED_CODE) {
        this.setState('auth_error');
        this.handleError(new Error('WS auth refused (code 1008): clé API invalide ou révoquée'));
        return;
      }
      if (NORMAL_CLOSURE_CODES.has(event.code) && this.state === 'stopped') {
        return;
      }
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    this.setState('reconnecting');
    const delayMs = Math.max(this.backoff, INITIAL_BACKOFF_S) * 1000;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.backoff = nextBackoff(this.backoff);
      this.connect();
    }, delayMs);
  }

  private processMessage(raw: unknown): void {
    if (typeof raw !== 'string') return;
    let message: unknown;
    try {
      message = JSON.parse(raw);
    } catch {
      return;
    }
    if (typeof message !== 'object' || message === null) return;
    const msg = message as Record<string, unknown>;
    const type = msg.type;
    if (type === 'heartbeat') return;
    if (type !== 'signal') return;

    const payload = msg.payload;
    if (typeof payload !== 'object' || payload === null) return;

    // On fait confiance au core pour la forme du Signal — pas de validation
    // Pydantic-like en TS pour cette session. À renforcer si besoin avec zod.
    const signal = payload as Signal;
    this.dispatch(signal);
  }

  private dispatch(signal: Signal): void {
    this.callbacks.onSignal?.(signal);

    if (signal.advisory?.macro_crash_warning) {
      this.callbacks.onCrashWarning?.(signal);
    }
    if (signal.circuit_breaker_status && signal.circuit_breaker_status !== 'ok') {
      this.callbacks.onFakeNewsDetected?.(signal);
    }
    if (typeof signal.veracity === 'number' && signal.veracity < this.veracityCollapseThreshold) {
      this.callbacks.onVeracityCollapse?.(signal);
    }
  }

  private setState(state: ConnectionState): void {
    if (this.state === state) return;
    this.state = state;
    this.callbacks.onStateChange?.(state);
  }

  private handleError(error: Error): void {
    this.callbacks.onError?.(error);
  }
}
