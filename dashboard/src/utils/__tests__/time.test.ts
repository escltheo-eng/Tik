/** parseUtcIso / timeAgo / timeUntil — le cœur du fix Bug 8. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { parseUtcIso, timeAgo, timeUntil } from '@/src/utils/time';

describe('parseUtcIso', () => {
  it('interprète un ISO naïf (sans timezone) comme UTC — le Bug 8', () => {
    const d = parseUtcIso('2026-07-02T10:00:00');
    expect(d.toISOString()).toBe('2026-07-02T10:00:00.000Z');
  });

  it("ne double-encode pas quand le suffixe Z est déjà là (ADR-013)", () => {
    const d = parseUtcIso('2026-07-02T10:00:00Z');
    expect(d.toISOString()).toBe('2026-07-02T10:00:00.000Z');
  });

  it('respecte un offset explicite non-UTC', () => {
    const d = parseUtcIso('2026-07-02T12:00:00+02:00');
    expect(d.toISOString()).toBe('2026-07-02T10:00:00.000Z');
  });

  it('gère les microsecondes du core (datetime Python)', () => {
    const d = parseUtcIso('2026-07-02T10:00:00.554767');
    expect(d.getTime()).toBeGreaterThan(0);
    expect(d.toISOString().startsWith('2026-07-02T10:00:00')).toBe(true);
  });
});

describe('timeAgo / timeUntil (horloge figée)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-02T12:00:00Z'));
  });
  afterEach(() => vi.useRealTimers());

  it("timeAgo d'un signal émis il y a 5 min ne montre PAS 2h05 (Bug 8)", () => {
    // Timestamp naïf comme le core en émettait : sans parseUtcIso, un client
    // en UTC+2 afficherait « il y a 2 h 5 min ».
    const label = timeAgo('2026-07-02T11:55:00');
    expect(label).toMatch(/5/);
    expect(label).not.toMatch(/h/i);
  });

  it('timeUntil est cohérent pour une cible dans 90 min', () => {
    const label = timeUntil('2026-07-02T13:30:00Z');
    expect(label.length).toBeGreaterThan(0);
    expect(label).toMatch(/1|90/); // « dans 1 h 30 » ou « dans 90 min » selon le format
  });
});
