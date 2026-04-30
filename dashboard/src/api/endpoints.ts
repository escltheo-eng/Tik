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
  Health,
  Signal,
  SourceVeracity,
  VeracityStatus,
} from './types';

// ----- Health -----

export async function getHealth(client: HttpClient): Promise<Health> {
  return client.get<Health>('/health', undefined, { authenticated: false });
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
