/**
 * Règles de dérivation des alertes depuis un Signal — SOURCE UNIQUE DE VÉRITÉ.
 *
 * Extraites de TikStream.dispatch (audit D-2, 2026-07-02) pour être partagées
 * entre le flux WS temps réel ET le rattrapage REST (resync) : les deux chemins
 * doivent produire exactement les mêmes alertes, sinon le rattrapage « invente »
 * ou « rate » des alertes par dérive de logique.
 *
 * Fonctions pures, sans IO — trivialement testables.
 */

import type { Signal } from '@/src/api/types';

export type DerivedAlertType = 'crash_warning' | 'fake_news_detected' | 'veracity_collapse';

/**
 * Types d'alerte déclenchés par ce signal (0..3).
 *
 * Règles (identiques à l'ancien TikStream.dispatch) :
 * - `crash_warning`     : advisory.macro_crash_warning présent (truthy) ;
 * - `fake_news_detected`: circuit_breaker_status ≠ 'ok' — SAUF horizon micro
 *   (toujours degraded by-design, shadow ML ADR-030/034) ;
 * - `veracity_collapse` : veracity < seuil — SAUF micro (défaut 0.70
 *   conservateur, pas un effondrement d'accord des sources).
 */
export function deriveAlertTypes(
  signal: Signal,
  veracityCollapseThreshold: number,
): DerivedAlertType[] {
  const types: DerivedAlertType[] = [];
  const isMicroShadow = signal.horizon === 'micro';

  if (signal.advisory?.macro_crash_warning) {
    types.push('crash_warning');
  }
  if (signal.circuit_breaker_status && signal.circuit_breaker_status !== 'ok' && !isMicroShadow) {
    types.push('fake_news_detected');
  }
  if (
    typeof signal.veracity === 'number' &&
    signal.veracity < veracityCollapseThreshold &&
    !isMicroShadow
  ) {
    types.push('veracity_collapse');
  }
  return types;
}
