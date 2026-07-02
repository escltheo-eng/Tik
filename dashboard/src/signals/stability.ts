/**
 * Stabilité directionnelle générique (logique pure, zéro IO).
 *
 * Pendant de `flash/stability.ts` mais pour un horizon quelconque (utilisé pour
 * GOLD swing, qui n'a PAS de flash — ADR-005). Mesure si la direction des
 * derniers signaux d'un actif/horizon TIENT (stable) ou HÉSITE (bascule
 * long↔short). N'INFLUENCE rien (pas d'edge prouvé) : aide juste l'humain à
 * repérer un actif « hésitant » d'un coup d'œil.
 */

import { Signal } from '@/src/api/types';
import { parseUtcIso } from '@/src/utils/time';

export type DirStabilityState = 'stable' | 'hesitant' | 'no_data';

export interface DirectionStability {
  state: DirStabilityState;
  count: number; // signaux de l'actif/horizon dans la fenêtre
  flips: number; // bascules long↔short consécutives
  currentDirection: string;
  windowHours: number;
}

const OPPOSITE: Record<string, string> = { long: 'short', short: 'long' };

export function computeDirectionStability(
  signals: Signal[],
  opts: { entityId: string; horizon: string; windowHours?: number; nowMs?: number },
): DirectionStability {
  const windowHours = opts.windowHours ?? 48;
  const nowMs = opts.nowMs ?? Date.now();
  const cutoff = nowMs - windowHours * 3_600_000;

  const filtered = signals.filter(
    (s) =>
      s.entity_id === opts.entityId &&
      s.horizon === opts.horizon &&
      parseUtcIso(s.timestamp).getTime() >= cutoff,
  );

  const count = filtered.length;
  const currentDirection = filtered[0]?.direction ?? 'neutral';

  // Ordre chrono pour compter les bascules opposées entre signaux directionnels.
  const chrono = [...filtered].reverse();
  const directional = chrono.filter((s) => s.direction === 'long' || s.direction === 'short');
  let flips = 0;
  for (let i = 1; i < directional.length; i++) {
    if (directional[i].direction === OPPOSITE[directional[i - 1].direction]) flips += 1;
  }

  let state: DirStabilityState;
  if (count < 2 || directional.length < 2) state = 'no_data';
  else if (flips === 0) state = 'stable';
  else state = 'hesitant';

  return { state, count, flips, currentDirection, windowHours };
}
