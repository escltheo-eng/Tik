/**
 * Modèles TypeScript miroirs des schémas du core.
 *
 * Source de vérité : `core/src/tik_core/storage/schemas.py` (Pydantic).
 * Référence Python parallèle : `sdk/src/tik_sdk/models.py`.
 *
 * Toute évolution côté core implique une mise à jour de ce fichier.
 * À terme on pourra publier l'OpenAPI du core et auto-générer ce module.
 *
 * Note : les datetime sont reçus en string ISO 8601 dans les payloads JSON.
 */

export interface Health {
  status: string;
  version: string;
  env: string;
}

export interface Entity {
  id: string;
  domain: string;
  namespace: string;
  metadata_json: Record<string, unknown>;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Evidence {
  source: string;
  score: number;
  fact: string;
}

export interface Trigger {
  type: string;
  value: string;
  weight: number;
}

export interface CounterScenario {
  name: string;
  probability: number;
  mitigation: string;
}

export interface Advisory {
  bias_on_existing_positions: string | null;
  macro_crash_warning: boolean;
  notes: string | null;
  // Champs ADR-012 (LLM hypothesis generator) — optionnels.
  // Présents selon le mode TIK_LLM_HYPOTHESIS_MODE :
  //   shadow → llm_hypothesis_candidate (sortie LLM en validation passive)
  //   active → template_hypothesis (ancien template conservé pour audit)
  llm_hypothesis_candidate?: string;
  template_hypothesis?: string;
}

export type Direction = 'long' | 'short' | 'neutral';
export type Horizon = 'flash' | 'swing' | 'macro';
export type CircuitBreakerStatus = 'ok' | 'degraded' | 'tripped';

export interface Signal {
  id: string;
  timestamp: string;
  entity_id: string;
  horizon: string;
  direction: string;
  confidence: number;
  veracity: number;
  hypothesis: string | null;
  counter_scenarios: CounterScenario[];
  evidence: Evidence[];
  triggers: Trigger[];
  sources_count: number;
  expiry: string | null;
  advisory: Advisory;
  circuit_breaker_status: string;
}

export interface VeracityStatus {
  global_veracity: number;
  sources_count_active: number;
  last_computed: string;
  status: string;
}

export interface SourceVeracity {
  id: string;
  name: string;
  category: string;
  current_veracity: number;
  tier: number;
  active: boolean;
}

// ----- Headlines (Phase 1 trading manuel J+10) -----

export type HeadlineSentiment = 'bull' | 'bear' | 'neutral';

export interface Headline {
  title: string;
  url: string | null;
  publisher: string;
  source: string;
  credibility: number;
  sentiment: string;
  published_at: string | null;
  fetched_at: string;
}

// ----- Hit rate (Phase A.2 trading manuel J+10) -----

export interface HitRate {
  entity_id: string;
  horizon: string;
  since_days: number;
  threshold_pct: number;
  measure_hours: number;
  n_total: number;
  n_evaluated: number;
  n_skipped: number;
  n_success: number;
  n_flagged_excluded: number;
  include_flagged: boolean;
  hit_rate: number;
  avg_gain_pct: number;
  sample_warning: string | null;
  computed_at: string;
  cache_hit: boolean;
}
