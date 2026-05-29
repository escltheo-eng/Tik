/**
 * Wrappers typés autour de `HttpClient`.
 *
 * Source de vérité côté core : `core/src/tik_core/api/`. À chaque ajout
 * d'un endpoint dans le core, ajouter ici un wrapper typé.
 *
 * Ce module est volontairement plat (pas de classe, juste des fonctions),
 * ce qui simplifie l'usage côté hooks et composants.
 */

import { HttpClient } from './client';
import {
  Entity,
  FeedbackPayload,
  FeedbackResponse,
  Headline,
  Health,
  HitRate,
  HitRateByVeracity,
  MacroEvent,
  MacroReading,
  PolymarketSnapshot,
  Signal,
  SignalFreshness,
  SignalTrackRecord,
  SourceHealth,
  SourceVeracity,
  VeracityStatus,
} from './types';

// ----- Health -----

export async function getHealth(client: HttpClient): Promise<Health> {
  return client.get<Health>('/health', undefined, { authenticated: false });
}

// M4 (audit 2026-05-24) — fraîcheur des signaux (détection panne silencieuse).
export async function getSignalFreshness(
  client: HttpClient,
  thresholdSeconds?: number,
): Promise<SignalFreshness> {
  return client.get<SignalFreshness>('/metrics/signal_freshness', {
    threshold_seconds: thresholdSeconds,
  });
}

// Santé par source OSINT (2026-05-28) — dégradation silencieuse par source.
export async function getSourceHealth(client: HttpClient): Promise<SourceHealth> {
  return client.get<SourceHealth>('/metrics/source_health');
}

// ----- Entities -----

export async function listEntities(
  client: HttpClient,
  options: { activeOnly?: boolean } = {},
): Promise<Entity[]> {
  return client.get<Entity[]>('/entities', {
    active_only: options.activeOnly ?? true,
  });
}

export async function getEntity(client: HttpClient, id: string): Promise<Entity> {
  return client.get<Entity>(`/entities/${encodeURIComponent(id)}`);
}

// ----- Signals -----

export interface LatestSignalsParams {
  entity?: string;
  horizon?: string;
  limit?: number;
}

export async function getLatestSignals(
  client: HttpClient,
  params: LatestSignalsParams = {},
): Promise<Signal[]> {
  return client.get<Signal[]>('/signals/latest', {
    entity: params.entity,
    horizon: params.horizon,
    limit: params.limit ?? 20,
  });
}

export async function getSignal(client: HttpClient, id: string): Promise<Signal> {
  return client.get<Signal>(`/signals/${encodeURIComponent(id)}`);
}

export interface SearchSignalsParams {
  entity?: string;
  horizon?: string;
  direction?: string;
  minConfidence?: number;
  minVeracity?: number;
  sinceHours?: number;
  limit?: number;
}

export async function searchSignals(
  client: HttpClient,
  params: SearchSignalsParams = {},
): Promise<Signal[]> {
  return client.get<Signal[]>('/signals', {
    entity: params.entity,
    horizon: params.horizon,
    direction: params.direction,
    min_confidence: params.minConfidence ?? 0,
    min_veracity: params.minVeracity ?? 0,
    since_hours: params.sinceHours ?? 24,
    limit: params.limit ?? 100,
  });
}

// ----- Veracity -----

export async function getGlobalVeracity(client: HttpClient): Promise<VeracityStatus> {
  return client.get<VeracityStatus>('/veracity/global');
}

export async function listSources(
  client: HttpClient,
  options: { activeOnly?: boolean } = {},
): Promise<SourceVeracity[]> {
  return client.get<SourceVeracity[]>('/veracity/sources', {
    active_only: options.activeOnly ?? true,
  });
}

export async function getSource(client: HttpClient, id: string): Promise<SourceVeracity> {
  return client.get<SourceVeracity>(`/veracity/sources/${encodeURIComponent(id)}`);
}

// ----- Headlines (Phase 1 trading manuel J+10) -----

export interface TopHeadlinesParams {
  limit?: number;
  sinceHours?: number;
  sort?: 'credibility_recency' | 'recency';
}

export async function getTopHeadlines(
  client: HttpClient,
  entityId: string,
  params: TopHeadlinesParams = {},
): Promise<Headline[]> {
  return client.get<Headline[]>(
    `/headlines/${encodeURIComponent(entityId)}`,
    {
      limit: params.limit ?? 10,
      since_hours: params.sinceHours ?? 24,
      sort: params.sort ?? 'credibility_recency',
    },
  );
}

// ----- Lecture macro (éducatif curé + réaction mesurée, SHADOW) -----

export async function getMacroReading(client: HttpClient): Promise<MacroReading[]> {
  return client.get<MacroReading[]>('/macro_reading');
}

// ----- Polymarket (marchés prédictifs, SHADOW — contexte de marché) -----

export interface PolymarketParams {
  limit?: number;
}

export async function getPolymarketMarkets(
  client: HttpClient,
  entityId: string,
  params: PolymarketParams = {},
): Promise<PolymarketSnapshot> {
  return client.get<PolymarketSnapshot>(`/polymarket/${encodeURIComponent(entityId)}`, {
    limit: params.limit ?? 10,
  });
}

// ----- Macro events (Lacune B Phase B1 trading manuel J+10) -----

export interface MacroEventsParams {
  hours?: number;
  importance?: ('HIGH' | 'MEDIUM' | 'LOW')[];
  entityId?: string;
  limit?: number;
}

export async function getUpcomingMacroEvents(
  client: HttpClient,
  params: MacroEventsParams = {},
): Promise<MacroEvent[]> {
  return client.get<MacroEvent[]>('/macro_events/upcoming', {
    hours: params.hours ?? 168,
    importance: params.importance?.join(','),
    entity_id: params.entityId,
    limit: params.limit ?? 50,
  });
}

export async function getMacroEventsHistory(
  client: HttpClient,
  params: { sinceDays?: number; importance?: ('HIGH' | 'MEDIUM' | 'LOW')[]; entityId?: string; limit?: number } = {},
): Promise<MacroEvent[]> {
  return client.get<MacroEvent[]>('/macro_events/history', {
    since_days: params.sinceDays ?? 30,
    importance: params.importance?.join(','),
    entity_id: params.entityId,
    limit: params.limit ?? 200,
  });
}

// ----- Hit rate (Phase A.2 trading manuel J+10) -----

export interface HitRateParams {
  sinceDays?: number;
  thresholdPct?: number;
  includeFlagged?: boolean;
}

export async function getHitRate(
  client: HttpClient,
  entityId: string,
  horizon: string,
  params: HitRateParams = {},
): Promise<HitRate> {
  return client.get<HitRate>('/metrics/hit_rate', {
    entity_id: entityId,
    horizon,
    since_days: params.sinceDays ?? 30,
    threshold_pct: params.thresholdPct,
    include_flagged: params.includeFlagged ?? false,
  });
}

export async function getHitRateByVeracity(
  client: HttpClient,
  entityId: string,
  horizon: string,
  params: HitRateParams = {},
): Promise<HitRateByVeracity> {
  return client.get<HitRateByVeracity>('/metrics/hit_rate_by_veracity', {
    entity_id: entityId,
    horizon,
    since_days: params.sinceDays ?? 30,
    threshold_pct: params.thresholdPct,
    include_flagged: params.includeFlagged ?? false,
  });
}

// ----- Track record (Phase A.3 trading manuel J+10) -----

export async function getSignalTrackRecord(
  client: HttpClient,
  signalId: string,
): Promise<SignalTrackRecord> {
  return client.get<SignalTrackRecord>(
    `/metrics/signal_track_record/${encodeURIComponent(signalId)}`,
  );
}

// ----- Feedback (Phase C Session 2 trading manuel J+10) -----

/**
 * POST /api/v1/feedback : alimente la recalibration source credibility ADR-011.
 * Scope requis : `write:feedback`. Si la clé API du dashboard n'a pas ce scope,
 * l'appel échoue 401/403 — le caller doit swallow et logger (cf.
 * `useAutoResolveWatchlist`).
 */
export async function reportFeedback(
  client: HttpClient,
  payload: FeedbackPayload,
): Promise<FeedbackResponse> {
  return client.post<FeedbackResponse>('/feedback', payload);
}
