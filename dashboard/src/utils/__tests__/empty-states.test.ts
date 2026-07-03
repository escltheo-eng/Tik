/** États vides honnêtes de la liste Signals (Contrat des 4 états, état ✋). */
import { describe, expect, it } from 'vitest';

import { emptyStateMessage } from '@/src/utils/empty-states';

describe('emptyStateMessage', () => {
  it('macro : dit clairement que le moteur n\'existe pas (backlog)', () => {
    const msg = emptyStateMessage('BTC', 'macro');
    expect(msg).toContain('✋');
    expect(msg).toContain('backlog');
    // Ne promet PAS que des signaux vont arriver
    expect(msg).not.toContain('apparaîtront ici');
  });

  it('GOLD + flash : le flash GOLD existe (PAXG, ADR-040) — explique la fenêtre marché', () => {
    // MAJ 2026-07-03 : l'ancien « pas de flash GOLD par design (ADR-005) » est
    // périmé depuis le flash GOLD via proxy PAXG. Le vide s'explique par le
    // marché fermé ou l'absence de transition, pas par un moteur inexistant.
    const msg = emptyStateMessage('GOLD', 'flash');
    expect(msg).toContain('PAXG');
    expect(msg).toContain('ADR-040');
    expect(msg).not.toContain('ADR-005');
    expect(msg).not.toContain('apparaîtront ici');
  });

  it('GOLD + micro : micro = BTC uniquement', () => {
    expect(emptyStateMessage('GOLD', 'micro')).toContain('BTC');
  });

  it('BTC + flash vide : message générique (des signaux VONT arriver)', () => {
    expect(emptyStateMessage('BTC', 'flash')).toContain('apparaîtront ici');
  });

  it('sans filtre : message générique', () => {
    expect(emptyStateMessage(undefined, undefined)).toContain('apparaîtront ici');
  });
});
