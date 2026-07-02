/**
 * Fenêtres de discipline macro — logique PURE (sans I/O), testable en isolation.
 *
 * Garde-fou 2-bis (CLAUDE.md §5) : ne pas entrer en swing dans les ±4 h autour
 * d'un event macro HIGH (FOMC, NFP, CPI, BCE, BoJ…). Si on doit absolument trader
 * autour d'un event, sizing divisé par 2.
 *
 * ⚠️ DISCIPLINE / CONTEXTE, PAS un signal : volatilité accrue autour de ces dates,
 * JAMAIS une prédiction de sens (Axe #1, NO-GO directionnel). Ne touche jamais
 * combined_bias/veracity/direction.
 *
 * Module self-contained (aucune dépendance) → compilable et testable seul, comme
 * `sessions.ts`. Le filtrage HIGH se fait ICI (pas côté serveur) pour éviter tout
 * risque de mismatch de casse/paramètre sur l'endpoint `/macro_events/upcoming`.
 */

export interface DisciplineEvent {
  event_name: string;
  scheduled_for: string; // ISO (le backend émet un suffixe Z, ADR-013)
  importance: string; // "HIGH" | "MEDIUM" | "LOW"
  assets_impacted?: string[];
}

export interface DisciplineRow {
  event: DisciplineEvent;
  whenMs: number; // instant de l'event (epoch ms)
  inWindow: boolean; // |now - event| <= 4 h
}

export interface DisciplineState {
  /** Event HIGH dont on est à ±4 h (le plus proche de maintenant), sinon null. */
  windowEvent: DisciplineRow | null;
  /** Prochains events HIGH FUTURS, triés par date croissante (cap `limit`). */
  upcoming: DisciplineRow[];
}

const TZ_SUFFIX_RE = /[Zz]|[+\-]\d{2}:?\d{2}$/;

/** ±4 h en millisecondes (fenêtre du Garde-fou 2-bis). */
export const DISCIPLINE_WINDOW_MS = 4 * 60 * 60 * 1000;

function isoToMs(iso: string): number {
  // Robuste si le backend oublie un jour le suffixe Z (cf. parseUtcIso, bug 8).
  return new Date(TZ_SUFFIX_RE.test(iso) ? iso : `${iso}Z`).getTime();
}

export function computeDisciplineState(
  nowMs: number,
  events: DisciplineEvent[],
  limit = 3,
): DisciplineState {
  const high = events
    .filter((e) => (e.importance ?? '').toUpperCase() === 'HIGH')
    .map((e) => {
      const whenMs = isoToMs(e.scheduled_for);
      return {
        event: e,
        whenMs,
        inWindow: Math.abs(whenMs - nowMs) <= DISCIPLINE_WINDOW_MS,
      };
    })
    .filter((r) => !Number.isNaN(r.whenMs))
    .sort((a, b) => a.whenMs - b.whenMs);

  const inWindowRows = high.filter((r) => r.inWindow);
  const windowEvent =
    inWindowRows.length > 0
      ? inWindowRows.reduce((a, b) =>
          Math.abs(a.whenMs - nowMs) <= Math.abs(b.whenMs - nowMs) ? a : b,
        )
      : null;

  const upcoming = high.filter((r) => r.whenMs > nowMs).slice(0, limit);

  return { windowEvent, upcoming };
}
