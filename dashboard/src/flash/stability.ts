/**
 * Stabilité flash — logique pure (testable, zéro IO).
 *
 * Diagnostic (2026-05-30) : la direction d'un signal flash BTC dérive de la
 * moyenne de 2 sources microstructure discrètes (carnet d'ordres + flux
 * agressif) face à un seuil ±0.30, sans hystérésis. Conséquence mesurée :
 * ~31 bascules long↔short opposées en <20 min sur 24 h. Le flash n'a aucun
 * edge directionnel démontré (go/no-go 2026-05-27).
 *
 * Ce module NE modifie PAS le moteur. Il lit les signaux déjà reçus et en
 * dérive un verdict de stabilité + un croisement des 2 sources, pour aider
 * l'humain à décider de NE PAS trader quand c'est instable / contradictoire.
 */

import { Signal } from '@/src/api/types';
import { parseUtcIso } from '@/src/utils/time';

export type FlashState = 'choppy' | 'stable' | 'indecisive' | 'no_data';
export type SourceBias = 'bull' | 'bear' | 'neutral' | 'unknown';
export type Agreement = 'agree' | 'conflict' | 'partial' | 'unknown';

export interface SourceReading {
  bias: SourceBias;
  detail: string | null; // ex. "OBI=+0.62" — contenu entre parenthèses du trigger
}

export interface CrossSource {
  orderbook: SourceReading;
  aggression: SourceReading;
  agreement: Agreement;
}

export interface FlashStability {
  state: FlashState;
  count: number; // nb de signaux flash dans la fenêtre
  flips: number; // bascules long↔short opposées (consécutives, directionnelles)
  currentDirection: string; // direction du dernier signal flash
  directionHeldMinutes: number | null; // depuis combien de temps la direction tient
  windowMinutes: number;
  latestTimestamp: string | null;
  cross: CrossSource | null;
}

const OPPOSITE: Record<string, string> = { long: 'short', short: 'long' };

/** Déduit le biais d'un trigger flash à partir de sa chaîne `value`. */
function biasFromTriggerValue(value: string): SourceBias {
  const v = value.toLowerCase();
  if (v.endsWith('bull')) return 'bull';
  if (v.endsWith('bear')) return 'bear';
  if (v.includes('neutral')) return 'neutral';
  return 'unknown';
}

/** Extrait le contenu entre parenthèses (ex. "OBI=+0.62"). */
function detailFromTriggerValue(value: string): string | null {
  const m = value.match(/\(([^)]+)\)/);
  return m ? m[1] : null;
}

function readSource(signal: Signal, triggerType: string): SourceReading {
  const t = signal.triggers.find((x) => x.type === triggerType);
  if (!t) return { bias: 'unknown', detail: null };
  return { bias: biasFromTriggerValue(t.value), detail: detailFromTriggerValue(t.value) };
}

function computeAgreement(ob: SourceBias, ag: SourceBias): Agreement {
  if (ob === 'unknown' && ag === 'unknown') return 'unknown';
  const dirs = [ob, ag];
  if (dirs.includes('bull') && dirs.includes('bear')) return 'conflict';
  if (ob === ag && (ob === 'bull' || ob === 'bear')) return 'agree';
  return 'partial';
}

/** Croisement carnet (OBI) vs flux agressif (taker) sur un signal flash donné. */
export function crossFromSignal(signal: Signal): CrossSource {
  const orderbook = readSource(signal, 'orderbook_imbalance');
  const aggression = readSource(signal, 'trade_aggression');
  return {
    orderbook,
    aggression,
    agreement: computeAgreement(orderbook.bias, aggression.bias),
  };
}

/**
 * Calcule la stabilité flash sur une fenêtre glissante.
 *
 * @param signals liste déjà triée récent→ancien (convention core)
 */
export function computeFlashStability(
  signals: Signal[],
  opts: { entityId?: string; windowMinutes?: number; nowMs?: number } = {},
): FlashStability {
  const entityId = opts.entityId ?? 'BTC';
  const windowMinutes = opts.windowMinutes ?? 45;
  const nowMs = opts.nowMs ?? Date.now();
  const cutoff = nowMs - windowMinutes * 60_000;

  const flash = signals.filter(
    (s) =>
      s.entity_id === entityId &&
      s.horizon === 'flash' &&
      parseUtcIso(s.timestamp).getTime() >= cutoff,
  );

  const count = flash.length;
  const latest = flash[0] ?? null;
  const currentDirection = latest?.direction ?? 'neutral';

  // Bascules opposées (long↔short) parmi les signaux directionnels, en ordre chrono.
  const chrono = [...flash].reverse();
  const directional = chrono.filter((s) => s.direction === 'long' || s.direction === 'short');
  let flips = 0;
  for (let i = 1; i < directional.length; i++) {
    if (directional[i].direction === OPPOSITE[directional[i - 1].direction]) flips += 1;
  }

  // Ancienneté de la direction actuelle : run contigu de même direction au plus récent.
  let runStartTs: string | null = latest ? latest.timestamp : null;
  if (latest) {
    for (let i = 1; i < flash.length; i++) {
      if (flash[i].direction === currentDirection) runStartTs = flash[i].timestamp;
      else break;
    }
  }
  const directionHeldMinutes = runStartTs
    ? Math.max(0, Math.round((nowMs - parseUtcIso(runStartTs).getTime()) / 60_000))
    : null;

  let state: FlashState;
  if (count < 2) {
    state = 'no_data';
  } else if (flips >= 2) {
    state = 'choppy';
  } else if (
    flips === 0 &&
    (currentDirection === 'long' || currentDirection === 'short') &&
    directional.length >= 2
  ) {
    state = 'stable';
  } else {
    state = 'indecisive';
  }

  return {
    state,
    count,
    flips,
    currentDirection,
    directionHeldMinutes,
    windowMinutes,
    latestTimestamp: latest?.timestamp ?? null,
    cross: latest ? crossFromSignal(latest) : null,
  };
}
