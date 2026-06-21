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

export interface NearMacroEvent {
  event_code: string;
  title: string;
  scheduled_for: string; // ISO-8601 UTC (suffixe Z)
  importance: string;
  hours_until: number; // signé : > 0 = event à venir, < 0 = event passé
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
  // Discipline macro (Phase B1.5) — posé par scoring/macro_proximity.py quand
  // le signal est émis dans la fenêtre ±4h d'un event HIGH impactant l'entité.
  near_macro_event?: NearMacroEvent;
  // Amplitude attendue (ADR-025) — volatilité réalisée typique sur l'horizon,
  // en % du prix. CONTEXTE de volatilité (« de combien ça bouge »), PAS une
  // prévision du sens. `ref_price` = prix à l'émission (→ conversion en points).
  expected_amplitude_pct?: number | null;
  ref_price?: number | null;
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
  /**
   * ADR-018 (refactor 2026-05-07) — Tik OSINT pure :
   * `confidence` = magnitude du `combined_bias` OSINT cross-validé ∈ [0, 1].
   * Sémantique uniforme (plus de double sens long/short vs neutral).
   * Affiché dans le dashboard sous le label "Conviction OSINT".
   * Le nom du champ reste `confidence` pour compatibilité avec les
   * signaux historiques (683 signaux pre-refactor en DB).
   */
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

// ----- Breaking news (ADR-027) -----
// Alerting / contexte / discipline — PAS un signal directionnel (ne touche
// jamais le combined_bias). Miroir de core/.../schemas.py:BreakingNewsItem.

export interface BreakingNewsItem {
  title: string;
  title_fr: string | null; // traduction auto (best-effort Ollama), peut être null
  source: string;
  url: string | null;
  category: string; // 'guerre/géopol' | 'politique US' | 'tarifs/commerce' | 'Fed/taux/macro' | 'crypto/régulation'
  keyword: string | null;
  published_at: string | null;
  detected_at: string | null;
}

// Réaction MESURÉE du BTC après une alerte (factuel a posteriori, PAS une prédiction).
export interface BreakingReaction {
  category: string;
  title: string;
  horizon_h: number;
  pct: number; // variation BTC
  btc0: number;
  btc1: number;
  gold_pct: number | null; // variation Or (null si indisponible)
  gold0: number | null;
  gold1: number | null;
  gold_closed: boolean; // or figé (marché fermé) → pas de mesure
  alerted_at: number; // epoch seconds
  measured_at: number; // epoch seconds
}

// ----- Macro events (Lacune B Phase B1 trading manuel J+10) -----

export type MacroImportance = 'HIGH' | 'MEDIUM' | 'LOW';

export interface MacroEvent {
  id: string;
  event_code: string;  // "FOMC_MEETING" | "NFP" | "CPI" | …
  event_name: string;
  scheduled_for: string;
  importance: string;
  assets_impacted: string[];
  source: string;  // "fred" | "fed_static"
  release_id: number | null;
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
  // Baseline constante "robot bête" sur les mêmes signaux (anti-surconfiance).
  // beats_baseline=true → Tik bat franchement le pari constant = avantage crédible
  // → le bandeau d'avertissement disparaît automatiquement.
  best_baseline_label?: 'long' | 'short' | 'neutral' | null;
  best_baseline_hit_rate?: number | null;
  beats_baseline?: boolean;
  sample_warning: string | null;
  computed_at: string;
  cache_hit: boolean;
}

// ----- Hit rate by veracity (Phase A.2-bis) -----

export interface HitRateByVeracityBucket {
  bucket_label: string;
  veracity_min: number;
  veracity_max: number;
  n_evaluated: number;
  n_skipped: number;
  n_success: number;
  hit_rate: number;
  avg_gain_pct: number;
}

export interface HitRateByVeracity {
  entity_id: string;
  horizon: string;
  since_days: number;
  threshold_pct: number;
  measure_hours: number;
  n_total_eligible: number;
  n_flagged_excluded: number;
  include_flagged: boolean;
  buckets: HitRateByVeracityBucket[];
  sample_warning: string | null;
  computed_at: string;
  cache_hit: boolean;
}

// ----- Feedback (Phase C Session 2 trading manuel J+10) -----

/**
 * Schéma POST /api/v1/feedback côté core (cf. `core/src/tik_core/storage/schemas.py:FeedbackIn`).
 * Vocabulaire trading-specific (`win` / `loss` / `breakeven` / `not_taken`).
 * Le mapping watchlist → feedback est fait dans `src/watchlist/outcome.ts`.
 */
export type FeedbackOutcome = 'win' | 'loss' | 'breakeven' | 'not_taken';

export interface FeedbackPayload {
  signal_id: string;
  trade_id?: string | null;
  outcome: FeedbackOutcome;
  pnl_points?: number | null;
  pnl_pct?: number | null;
  duration_held_s?: number | null;
  exit_reason?: string | null;
}

export interface FeedbackResponse {
  id: string;
  signal_id: string;
  client_id: string;
  outcome: string;
  received_at: string;
}

// ----- Track record (Phase A.3 trading manuel J+10) -----

export type TrackRecordBadge = 'correct' | 'raté' | 'données_manquantes' | 'en_attente';

export interface TrackRecordRow {
  label: string;          // "1h" | "6h" | "24h" | "5j"
  measure_hours: number;
  threshold_pct: number;
  available: boolean;
  target_iso: string;     // ISO UTC absolu de la cible (pour calcul "dans X")
  p0: number | null;
  p1: number | null;
  delta_pct: number | null;
  success: boolean | null;
  badge: string;          // TrackRecordBadge
}

export interface SignalTrackRecord {
  signal_id: string;
  entity_id: string;
  direction: string;
  horizon: string;
  rows: TrackRecordRow[];
  computed_at: string;
  cache_hit: boolean;
}

// M4 (audit 2026-05-24) — fraîcheur de la production de signaux.
export interface SignalFreshness {
  last_signal_at: string | null;
  age_seconds: number | null;
  stale: boolean;
  threshold_seconds: number;
}

// Santé par source OSINT (2026-05-28) — détection de dégradation silencieuse.
export interface SourceHealthItem {
  name: string;
  status: 'ok' | 'stale' | 'missing';
  age_seconds: number | null;
  max_age_seconds: number;
  critical: boolean;
  note: string;
}

export interface SourceHealth {
  checked_at: string;
  n_total: number;
  n_ok: number;
  n_stale: number;
  n_missing: number;
  any_critical_down: boolean;
  critical_down: string[];
  sources: SourceHealthItem[];
}

// ----- Polymarket (marchés prédictifs, SHADOW — contexte de marché) -----

export interface PolymarketMarket {
  question: string | null;
  threshold_usd: number | null;
  yes_prob: number | null;
  no_prob: number | null;
  volume: number | null;
  clob_token_id: string | null;
}

export interface PolymarketEvent {
  title: string | null;
  slug: string | null;
  end_date: string | null;
  n_markets: number;
  total_volume: number;
  markets: PolymarketMarket[];
}

export interface PolymarketSnapshot {
  source: string;
  entity: string;
  mode: string;
  fetched_at: string | null;
  n_events: number;
  total_volume: number;
  events: PolymarketEvent[];
}

// ----- Dérivés Binance (positionnement, SHADOW — contexte, ADR-023) -----

export interface DerivativesSnapshot {
  source: string;
  entity: string;
  mode: string;
  fetched_at: string | null;
  funding_rate: number | null;
  mark_price: number | null;
  next_funding_time: number | null;
  open_interest_btc: number | null;
  open_interest_usd: number | null;
  long_short_ratio_global: number | null;
  long_account_global: number | null;
  short_account_global: number | null;
  long_short_ratio_top: number | null;
  long_account_top: number | null;
  short_account_top: number | null;
}

// Couche éducative « Lecture macro » supprimée 2026-05-30 (cf. memory
// macro-reading-removed-2026-05-30 pour rebuild guide en Option C / liens externes).

// ----- Macro Regime / Cockpit (ADR-028, CONTEXTE objectif non-sentiment) -----
// Chiffres FRED officiels datés (bilan Fed, taux réels, proba récession) — pas
// d'affirmation, pas de LLM, ne touche jamais direction/veracity (contraste avec
// la « Lecture macro » supprimée). Lecture seule, contexte pur.

export interface MacroIndicator {
  value: number | null;
  date: string | null;
  series_id?: string | null;
}

export interface NetLiquidity {
  available: boolean;
  as_of: string | null;
  net_liquidity_busd: number | null; // milliards $
  net_liquidity_tusd: number | null; // trillions $
  n_weeks?: number | null;
  delta_4w_busd: number | null;
  delta_13w_busd: number | null;
  zscore_52w: number | null;
  regime: string | null; // expansion | contraction | neutral | unknown
  components?: Record<string, unknown> | null;
  context_only?: boolean;
}

export interface GlobalLiquidity {
  available: boolean;
  as_of: string | null;
  global_liquidity_busd: number | null;
  global_liquidity_tusd: number | null;
  n_weeks?: number | null;
  delta_4w_busd: number | null;
  delta_13w_busd: number | null;
  zscore_52w: number | null;
  regime: string | null;
  components?: Record<string, unknown> | null;
  context_only?: boolean;
}

export interface RiskSeries {
  value: number | null;
  date: string | null;
  n?: number | null;
  delta_20d: number | null;
  pct_rank_1y: number | null; // rang centile sur ~1 an (0..1) — élevé = stress élevé
  zscore_1y: number | null;
  series_id?: string | null;
}

// Régime de RISQUE (ADR-030) : VIX + spreads de crédit FRED. `risk_state` décrit
// l'environnement de risque (volatilité actions + tension crédit), JAMAIS une
// prédiction du prix BTC/GOLD. CONTEXTE strict (ne touche pas direction/veracity).
export interface RiskRegime {
  available: boolean;
  as_of: string | null;
  risk_state: string | null; // risk_on | risk_off | neutral | unknown
  stress_percentile: number | null; // moyenne centile VIX + HY (0..1)
  vix: RiskSeries | null;
  hy_oas: RiskSeries | null; // spread High Yield (% pts)
  ig_oas: RiskSeries | null; // spread Investment Grade (% pts)
  context_only?: boolean;
}

export interface MacroRegime {
  available: boolean;
  source?: string;
  fetched_at: string | null;
  net_liquidity: NetLiquidity | null;
  global_liquidity?: GlobalLiquidity | null;
  indicators: Record<string, MacroIndicator>;
  risk_regime?: RiskRegime | null;
  context_only?: boolean;
}

export interface RateMeeting {
  date: string;
  probabilities: Record<string, number>;
  hold: number | null;
  hike: number | null;
  cut: number | null;
  most_likely_range: string | null;
  most_likely_prob: number | null;
}

export interface RateProbabilities {
  available: boolean;
  source?: string;
  fetched_at: string | null;
  watch_date: string | null;
  current_range: string | null;
  effr: number | null;
  meetings: RateMeeting[];
  context_only?: boolean;
}

export interface MacroCockpit {
  regime: MacroRegime;
  rate_probabilities?: RateProbabilities | null;
  fear_greed: Record<string, unknown> | null;
  derivatives_btc: Record<string, unknown> | null;
  etf_flows_btc: Record<string, unknown> | null;
  cot_gold: Record<string, unknown> | null;
  polymarket_btc: Record<string, unknown> | null;
  next_macro_event: Record<string, unknown> | null;
}

// ----- Carnet de trades manuels (Levier B 2026-06-03) -----

export type TradeAlignment = 'with' | 'against' | 'none';

export interface ManualTrade {
  id: string;
  entity_id: string;
  direction: string; // "long" | "short"
  entry_time: string;
  entry_price: number;
  size_lots: number;
  stop_price: number | null;
  target_price: number | null;
  exit_time: string | null;
  exit_price: number | null;
  status: string; // "open" | "closed"
  note: string | null;
  result_pct: number | null;
  tik_signal_id: string | null;
  tik_direction: string | null; // "long" | "short" | "neutral"
  tik_veracity: number | null;
  tik_alignment: TradeAlignment | null;
  created_at: string;
  updated_at: string;
}

/** Payload de création (POST /trades). Les champs `tik_*` = snapshot contexte. */
export interface ManualTradeInput {
  entity_id: string;
  direction: 'long' | 'short';
  entry_price: number;
  size_lots: number;
  entry_time?: string | null;
  stop_price?: number | null;
  target_price?: number | null;
  note?: string | null;
  tik_signal_id?: string | null;
  tik_direction?: 'long' | 'short' | 'neutral' | null;
  tik_veracity?: number | null;
}

export interface ManualTradeCloseInput {
  exit_price: number;
  exit_time?: string | null;
  note?: string | null;
}

export interface ManualTradeGroupStats {
  n: number;
  win_rate: number | null;
  avg_result_pct: number | null;
  total_result_pct: number;
}

export interface ManualTradeStats {
  n_total: number;
  n_open: number;
  n_closed: number;
  win_rate: number | null;
  avg_result_pct: number | null;
  total_result_pct: number;
  by_alignment: {
    with: ManualTradeGroupStats;
    against: ManualTradeGroupStats;
    none: ManualTradeGroupStats;
  };
}
