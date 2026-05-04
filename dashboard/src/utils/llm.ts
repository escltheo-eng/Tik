/**
 * Helpers liés au LLM hypothesis generator (ADR-012).
 *
 * Le seuil "30 mots" est partagé entre la carte secondaire du détail
 * signal (`app/signal/[id].tsx`) et la carte "Stats LLM" de l'écran
 * Home. Centralisé ici pour qu'un futur ajustement (ex. 40 mots) se
 * fasse en un seul endroit.
 */

import { Signal } from '@/src/api/types';

export const MIN_LLM_HYPOTHESIS_WORDS = 30;

export function countWords(s: string | null | undefined): number {
  if (!s) return 0;
  return s.split(/\s+/).filter(Boolean).length;
}

/**
 * Valide qu'un texte candidate (mode shadow) atteint le seuil minimum.
 * Filet anti-fantôme : un texte trop court signale probablement un
 * fallback template stocké par erreur comme candidate.
 */
export function isLlmCandidateValid(candidate: string | null | undefined): boolean {
  return countWords(candidate) >= MIN_LLM_HYPOTHESIS_WORDS;
}

/**
 * Détermine si la sortie LLM a réussi pour un signal donné.
 *
 * Couvre les deux modes de TIK_LLM_HYPOTHESIS_MODE :
 *   - shadow : advisory.llm_hypothesis_candidate >= 30 mots
 *   - active : advisory.template_hypothesis présent ET
 *              signal.hypothesis >= 30 mots
 *   - disabled / fallback : aucun des deux
 */
export function isSignalLlmEnriched(signal: Signal): boolean {
  if (isLlmCandidateValid(signal.advisory.llm_hypothesis_candidate)) {
    return true;
  }
  if (
    signal.advisory.template_hypothesis &&
    countWords(signal.hypothesis) >= MIN_LLM_HYPOTHESIS_WORDS
  ) {
    return true;
  }
  return false;
}
