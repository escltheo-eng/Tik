/**
 * Config vitest — socle de tests dashboard (Phase C, 2026-07-02).
 *
 * Périmètre volontaire : les MODULES PURS uniquement (utils, api/ws,
 * watchlist/outcome, safety, alerts/derive) — aucun composant React Native
 * (qui exigerait jest-expo + mocks natifs, hors socle). Lancer : `npm test`.
 */
import path from 'path';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname),
    },
  },
  test: {
    include: ['src/**/__tests__/**/*.test.ts'],
    environment: 'node',
  },
});
