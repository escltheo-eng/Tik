/**
 * Feu de sécurité consolidé — l'« edge de non-perte » (2026-06-26).
 *
 * Fusionne en UN verdict (go / caution / stop) les freins qui existaient déjà
 * mais éparpillés sur le cockpit : discipline macro ±4h, série de pertes du
 * trader (carnet), régime risk-off (VIX/crédit), choc breaking-news récent.
 *
 * Rôle = répondre « ai-je le DROIT de trader maintenant, et à quelle taille ? »
 * — JAMAIS « achète » (Axe #1, aucune direction ici). C'est le futur GATE qui
 * modulera un signal de prédiction validé : stop → skip, caution → sizing ÷2,
 * go → taille normale. Logique PURE (testable, sans I/O).
 *
 * Règle de stop personnelle (choix trader 2026-06-26) : 2 trades perdants
 * d'affilée → STOP.
 */

export type SafetyLevel = 'go' | 'caution' | 'stop';

export interface SafetyReason {
  level: 'stop' | 'caution';
  text: string;
}

export interface TradeSafety {
  level: SafetyLevel;
  /** Sizing conseillé qui découle du niveau (modulateur pour la prédiction). */
  sizingFactor: number; // stop → 0, caution → 0.5, go → 1
  reasons: SafetyReason[];
}

/** Event macro bloquant (±4h d'un HIGH) — forme minimale utilisée ici. */
export interface MacroBlock {
  event_name: string;
}

/** Trade du carnet — sous-ensemble des champs nécessaires. */
export interface SafetyTrade {
  status: string; // "open" | "closed"
  result_pct: number | null;
  exit_time: string | null;
  entity_id?: string; // pour la concentration (positions empilées)
  direction?: string; // "long" | "short"
}

/** Item breaking — sous-ensemble. */
export interface SafetyBreaking {
  detected_at: string | null;
  category: string;
}

// Seuils (calibrage initial — ajustables).
export const CONSECUTIVE_LOSS_STOP = 2; // ta règle : 2 pertes d'affilée → STOP
const BREAKING_FRESH_MS = 2 * 3600 * 1000; // un breaking < 2h = marché nerveux
export const CONCENTRATION_STACK = 2; // ≥ 2 positions même actif+sens = empilement

/**
 * Nombre de trades CLÔTURÉS perdants consécutifs, en partant du plus récent.
 * S'arrête au premier gain (« d'affilée »). Auto-réinitialisé par un trade gagnant.
 */
export function consecutiveLosses(trades: SafetyTrade[]): number {
  const closed = trades
    .filter((t) => t.status === 'closed' && t.result_pct != null && t.exit_time)
    .sort((a, b) => (b.exit_time as string).localeCompare(a.exit_time as string));
  let n = 0;
  for (const t of closed) {
    if ((t.result_pct as number) < 0) n += 1;
    else break;
  }
  return n;
}

export function computeTradeSafety(input: {
  macroBlock: MacroBlock | null;
  trades: SafetyTrade[];
  riskState: string | null; // "risk_off" | "neutral" | "risk_on" | "unknown" | null
  breaking: SafetyBreaking[];
  nowMs: number;
}): TradeSafety {
  const reasons: SafetyReason[] = [];

  // --- Freins DURS (→ stop) ---
  if (input.macroBlock) {
    reasons.push({
      level: 'stop',
      text: `Event macro HIGH ±4h (${input.macroBlock.event_name}) — ne pas entrer en swing`,
    });
  }
  const losses = consecutiveLosses(input.trades);
  if (losses >= CONSECUTIVE_LOSS_STOP) {
    reasons.push({
      level: 'stop',
      text: `${losses} pertes d'affilée — STOP pour aujourd'hui (ta règle). Coupe, fais une pause.`,
    });
  }

  // --- Freins SOUPLES (→ caution) ---
  if (losses === 1) {
    reasons.push({ level: 'caution', text: '1 perte récente — vigilance avant la suivante' });
  }
  if (input.riskState === 'risk_off') {
    reasons.push({
      level: 'caution',
      text: 'Marché en stress (risk-off VIX/crédit) — volatilité accrue',
    });
  }
  const freshBreaking = input.breaking.find((b) => {
    if (!b.detected_at) return false;
    const t = Date.parse(b.detected_at.endsWith('Z') ? b.detected_at : `${b.detected_at}Z`);
    return !Number.isNaN(t) && input.nowMs - t <= BREAKING_FRESH_MS;
  });
  if (freshBreaking) {
    reasons.push({
      level: 'caution',
      text: `Actu breaking récente (${freshBreaking.category}) — marché potentiellement nerveux`,
    });
  }

  // --- Concentration : positions OUVERTES empilées (même actif + même sens) ---
  // Le vrai risque de concentration d'un trader mono-actif : empiler du BTC dans
  // le même sens sans le réaliser → exposition réelle > exposition perçue.
  const openByKey = new Map<string, { n: number; entity: string; dir: string }>();
  for (const t of input.trades) {
    if (t.status !== 'open' || !t.entity_id || !t.direction) continue;
    const key = `${t.entity_id}:${t.direction}`;
    const cur = openByKey.get(key) ?? { n: 0, entity: t.entity_id, dir: t.direction };
    cur.n += 1;
    openByKey.set(key, cur);
  }
  for (const g of openByKey.values()) {
    if (g.n >= CONCENTRATION_STACK) {
      reasons.push({
        level: 'caution',
        text: `${g.n} positions ${g.entity} ${g.dir} ouvertes — exposition empilée (risque concentré)`,
      });
    }
  }

  const hasStop = reasons.some((r) => r.level === 'stop');
  const hasCaution = reasons.some((r) => r.level === 'caution');
  const level: SafetyLevel = hasStop ? 'stop' : hasCaution ? 'caution' : 'go';
  const sizingFactor = level === 'stop' ? 0 : level === 'caution' ? 0.5 : 1;

  return { level, sizingFactor, reasons };
}
