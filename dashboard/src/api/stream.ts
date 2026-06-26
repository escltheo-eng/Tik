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

  /**
   * Force une reconnexion immédiate, backoff réinitialisé.
   *
   * Cas d'usage : retour au premier plan sur mobile. iOS gèle la WebSocket en
   * arrière-plan ; au réveil le socket peut être "zombie" (paraît ouvert mais
   * ne reçoit plus rien) ou bloqué sur un long backoff (jusqu'à 60 s). On ferme
   * proprement l'ancien socket — en détachant ses handlers pour que son onclose
   * ne reprogramme PAS un reconnect concurrent — puis on rouvre tout de suite.
   * La reconnexion réussie repasse l'état à 'connected' (le consumer peut alors
   * déclencher un rattrapage REST des signaux manqués).
   */
  forceReconnect(): void {
    if (this.stopped) return;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.backoff = INITIAL_BACKOFF_S;
    const old = this.ws;
    this.ws = null;
    if (old !== null) {
      old.onopen = null;
      old.onmessage = null;
      old.onerror = null;
      old.onclose = null;
      try {
        old.close(1000, 'force reconnect');
      } catch {
        // ignore
      }
    }
    this.connect();
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

    // Validation minimale de la forme avant dispatch (audit 2026-05-24 M1/M3) :
    // le payload WS vient du réseau, on ne le caste plus aveuglément. On vérifie
    // les champs portants et on normalise `advisory` à {} si absent/non-objet,
    // pour qu'aucun consommateur ne crashe sur `signal.advisory.x`.
    const p = payload as Record<string, unknown>;
    if (typeof p.id !== 'string' || typeof p.entity_id !== 'string') return;
    if (typeof p.direction !== 'string' || typeof p.veracity !== 'number') return;
    if (p.advisory == null || typeof p.advisory !== 'object') {
      p.advisory = {};
    }
    const signal = payload as Signal;
    this.dispatch(signal);
  }

  private dispatch(signal: Signal): void {
    this.callbacks.onSignal?.(signal);

    if (signal.advisory?.macro_crash_warning) {
      this.callbacks.onCrashWarning?.(signal);
    }
    // Un signal micro (fusion ADR-033) est TOUJOURS circuit_breaker_status="degraded"
    // by-design (SHADOW strict) — ce n'est PAS un désaccord de sources OSINT. On l'exclut
    // donc du déclencheur anti-fake-news pour ne pas générer de fausses alertes "Fake news".
    if (
      signal.circuit_breaker_status &&
      signal.circuit_breaker_status !== 'ok' &&
      signal.horizon !== 'micro'
    ) {
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
