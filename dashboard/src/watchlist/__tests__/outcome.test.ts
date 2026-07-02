/** deriveOutcomeFromTrackRecord & co — le verdict affiché à la trader. */
import { describe, expect, it } from 'vitest';

import type { SignalTrackRecord, TrackRecordRow } from '@/src/api/types';
import {
  deriveOutcomeFromTrackRecord,
  isOutcomeLikelyAvailable,
  mapOutcomeToFeedback,
} from '@/src/watchlist/outcome';

function row(partial: Partial<TrackRecordRow>): TrackRecordRow {
  return {
    label: '1h',
    measure_hours: 1,
    threshold_pct: 0.1,
    available: true,
    target_iso: '2026-07-02T11:00:00Z',
    p0: 100,
    p1: 100,
    delta_pct: 0,
    success: null,
    badge: 'correct',
    ...partial,
  };
}

function record(direction: string, rows: TrackRecordRow[]): SignalTrackRecord {
  return {
    signal_id: 'TIK-TEST',
    entity_id: 'BTC',
    direction,
    horizon: 'flash',
    rows,
    computed_at: '2026-07-02T12:00:00Z',
    cache_hit: false,
  };
}

describe('deriveOutcomeFromTrackRecord', () => {
  it('reste pending tant que la fenêtre est incomplète (dernière ligne en_attente)', () => {
    const r = record('long', [
      row({ badge: 'correct', delta_pct: 0.5 }),
      row({ label: '5j', badge: 'en_attente', delta_pct: null }),
    ]);
    expect(deriveOutcomeFromTrackRecord(r)).toBeNull();
  });

  it('confirmed dès qu\'une ligne échue atteint le sens du signal', () => {
    const r = record('long', [
      row({ label: '15min', badge: 'raté', delta_pct: -0.3 }),
      row({ label: '1h', badge: 'correct', delta_pct: 0.4 }),
    ]);
    const out = deriveOutcomeFromTrackRecord(r);
    expect(out?.outcome).toBe('confirmed');
    expect(out?.sourceRowLabel).toBe('1h');
  });

  it('refuted quand aucune ligne dans le sens et au moins une contre', () => {
    const r = record('long', [row({ badge: 'raté', delta_pct: -0.5 })]);
    expect(deriveOutcomeFromTrackRecord(r)?.outcome).toBe('refuted');
  });

  it('inconclusive quand tout est sous le seuil (ça a stagné)', () => {
    const r = record('long', [row({ badge: 'correct', delta_pct: 0.05, threshold_pct: 0.1 })]);
    expect(deriveOutcomeFromTrackRecord(r)?.outcome).toBe('inconclusive');
  });

  it('n_a quand seules des données manquantes existent', () => {
    const r = record('long', [row({ badge: 'données_manquantes', delta_pct: null })]);
    expect(deriveOutcomeFromTrackRecord(r)?.outcome).toBe('n_a');
  });

  it('un short gagne quand le prix BAISSE au-delà du seuil', () => {
    const r = record('short', [row({ badge: 'raté', delta_pct: -0.5, threshold_pct: 0.1 })]);
    // delta -0.5 % sur un short = gain 0.5 % > seuil → confirmed, quel que soit
    // le badge binaire posé par le backend à l'instant contractuel.
    expect(deriveOutcomeFromTrackRecord(r)?.outcome).toBe('confirmed');
  });
});

describe('mapOutcomeToFeedback', () => {
  it('mappe vers le vocabulaire trading du core', () => {
    expect(mapOutcomeToFeedback('confirmed')).toBe('win');
    expect(mapOutcomeToFeedback('refuted')).toBe('loss');
    expect(mapOutcomeToFeedback('n_a')).toBe('not_taken');
  });

  it("n'envoie NI l'inconclusive NI le pending (pollution de calibration)", () => {
    expect(mapOutcomeToFeedback('inconclusive')).toBeNull();
    expect(mapOutcomeToFeedback('pending')).toBeNull();
  });
});

describe('isOutcomeLikelyAvailable', () => {
  const now = new Date('2026-07-02T12:00:00Z');

  it('flash : dispo ~1h après émission (marge -30 min incluse)', () => {
    expect(isOutcomeLikelyAvailable('2026-07-02T11:20:00Z', 'flash', now)).toBe(true);
    expect(isOutcomeLikelyAvailable('2026-07-02T11:50:00Z', 'flash', now)).toBe(false);
  });

  it('swing : PAS dispo au bout de 2h (fenêtre 5j)', () => {
    expect(isOutcomeLikelyAvailable('2026-07-02T10:00:00Z', 'swing', now)).toBe(false);
  });

  it("interprète un timestamp backend NAÏF comme UTC (fix audit 2026-07-02)", () => {
    // Sans parseUtcIso, un client UTC+2 croirait le signal plus vieux de 2h
    // → éligible à tort. 11:50 naïf = 11:50 UTC = 10 min → PAS éligible.
    expect(isOutcomeLikelyAvailable('2026-07-02T11:50:00', 'flash', now)).toBe(false);
  });

  it('micro : dispo ~2h après émission (clé ajoutée par la réconciliation ADR-034)', () => {
    expect(isOutcomeLikelyAvailable('2026-07-02T09:00:00Z', 'micro', now)).toBe(true);
    expect(isOutcomeLikelyAvailable('2026-07-02T11:00:00Z', 'micro', now)).toBe(false);
  });

  it('horizon inconnu → jamais éligible', () => {
    expect(isOutcomeLikelyAvailable('2026-07-02T09:00:00Z', 'inconnu', now)).toBe(false);
  });
});
