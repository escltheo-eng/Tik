/**
 * Affichage de l'amplitude attendue + libellés d'horizon précis (ADR-025).
 *
 * L'amplitude attendue = volatilité réalisée typique sur l'horizon
 * (`advisory.expected_amplitude_pct`, posée par le backend). C'est « de
 * combien le prix bouge typiquement sur cette durée », PAS une prévision du
 * sens : Tik n'a aucun edge directionnel mesuré (go/no-go 2026-05-27). Le
 * libellé d'affichage le rappelle explicitement (anti-vernis de certitude).
 */

import { pctToPoints, pointSizeFor } from './points';

/** Libellé court de l'horizon avec sa durée, pour les badges (carte + détail). */
export function horizonLabel(horizon: string): string {
  switch (horizon) {
    case 'flash':
      return 'flash · ~1h';
    case 'swing':
      return 'swing · ~5-7j';
    case 'macro':
      return 'macro · ~30j';
    default:
      return horizon;
  }
}

/** Fenêtre sur laquelle l'amplitude est mesurée, par horizon (cf. moteurs). */
export function amplitudeWindowLabel(horizon: string): string {
  switch (horizon) {
    case 'flash':
      return '~1 h';
    case 'swing':
      return '~5 j';
    case 'macro':
      return '~30 j';
    default:
      return '';
  }
}

/** % avec 2 décimales sous 1 %, 1 décimale au-dessus (lisibilité). */
export function formatAmplitudePct(pct: number): string {
  return pct < 1 ? pct.toFixed(2) : pct.toFixed(1);
}

/**
 * Entier avec séparateur de milliers (espace). Implémenté à la main : Hermes
 * (moteur JS de React Native) n'a pas toujours `Intl`/`toLocaleString` complet.
 */
export function formatPoints(pts: number): string {
  const n = Math.round(Math.abs(pts));
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

export interface AmplitudeDisplay {
  pctLabel: string; // ex. "±2.3%"
  pointsLabel: string | null; // ex. "≈ ±180 000 pts" ou null si non calibrable
  windowLabel: string; // ex. "~5 j"
}

/**
 * Construit l'affichage de l'amplitude pour un signal, ou null si la donnée
 * n'est pas présente (anciens signaux pré-ADR-025 → on n'affiche rien).
 */
export function amplitudeDisplay(
  entityId: string,
  horizon: string,
  expectedAmplitudePct?: number | null,
  refPrice?: number | null,
): AmplitudeDisplay | null {
  if (expectedAmplitudePct == null || expectedAmplitudePct <= 0) return null;

  const pctLabel = `±${formatAmplitudePct(expectedAmplitudePct)}%`;

  let pointsLabel: string | null = null;
  const pointSize = pointSizeFor(entityId);
  if (pointSize != null && refPrice != null && refPrice > 0) {
    const pts = pctToPoints(expectedAmplitudePct, refPrice, pointSize);
    pointsLabel = `≈ ±${formatPoints(pts)} pts`;
  }

  return { pctLabel, pointsLabel, windowLabel: amplitudeWindowLabel(horizon) };
}
