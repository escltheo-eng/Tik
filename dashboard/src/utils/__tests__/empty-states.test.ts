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

  it('GOLD + flash : explique le délai Yahoo 15 min (ADR-005)', () => {
    const msg = emptyStateMessage('GOLD', 'flash');
    expect(msg).toContain('✋');
    expect(msg).toContain('15 min');
    expect(msg).toContain('ADR-005');
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
