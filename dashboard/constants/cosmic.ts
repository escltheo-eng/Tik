/**
 * Palette « cosmique γ » — refonte UI (échantillon de validation 2026-06-15).
 *
 * Valeurs issues du prompt refonte de Théa. ADDITIF : ce fichier ne modifie
 * jamais `constants/theme.ts`. Toute la refonte vit sur la branche
 * `refonte-cosmique` → 100 % réversible (retour `main` = layout actuel).
 *
 * Anti « vernis de certitude » (Axe #1) : ces couleurs servent la lisibilité,
 * pas à faire passer la conviction/veracity pour des gages de fiabilité. Tik
 * n'a aucun edge directionnel prouvé (go/no-go 2026-05-27).
 */

import type { TextStyle } from 'react-native';

export const Cosmic = {
  bg: '#0a0c14',
  bgDeep: '#06070d',
  card: '#131826',
  cardAlt: '#1a2133',
  border: 'rgba(255,255,255,0.06)',
  borderStrong: 'rgba(255,255,255,0.12)',
  text: '#e8ecf5',
  textDim: 'rgba(232,236,245,0.62)',
  textFaint: 'rgba(232,236,245,0.38)',
  accent: '#f5b042', // ambre / safran
  long: '#6ec5a2', // vert doux (haussier)
  short: '#e87a7a', // rouge doux (baissier)
  neutral: '#e8b86b', // orange doux
  macro: '#7d9ed3', // bleu doux (info macro)
  btcSun: '#f5b042', // mini-soleil BTC (orange)
  goldSun: '#e8c873', // mini-soleil GOLD (doré)
} as const;

export interface DirectionMeta {
  color: string;
  label: string;
}

/** Couleur + libellé d'une direction de signal, palette douce cosmique. */
export function directionMeta(direction: string): DirectionMeta {
  switch (direction) {
    case 'long':
      return { color: Cosmic.long, label: 'LONG' };
    case 'short':
      return { color: Cosmic.short, label: 'SHORT' };
    default:
      return { color: Cosmic.neutral, label: 'NEUTRAL' };
  }
}

/** Couleur du mini-soleil par actif. */
export function sunColor(entityId: string): string {
  return entityId === 'GOLD' ? Cosmic.goldSun : Cosmic.btcSun;
}

/**
 * Ombres « relief / 3D » réutilisables pour les titres cosmiques. Effet de texte
 * surélevé : lumière implicite en haut-gauche → ombre portée en bas-droite, ce
 * qui détache le titre du fond et lui donne du volume.
 *
 * Note technique : React Native ne supporte qu'UNE ombre par `Text`, donc pas
 * d'extrusion multi-couches (qui exigerait d'empiler des `Text` en position
 * absolue — fragile en layout). Ce relief « une ombre » est robuste et rend bien
 * sur le fond sombre. `strong` pour les gros titres, `soft` pour les sous-titres.
 */
export const TitleShadow: { strong: TextStyle; soft: TextStyle } = {
  strong: {
    textShadowColor: 'rgba(0,0,0,0.6)',
    textShadowOffset: { width: 1, height: 2 },
    textShadowRadius: 4,
  },
  soft: {
    textShadowColor: 'rgba(0,0,0,0.5)',
    textShadowOffset: { width: 0.5, height: 1.5 },
    textShadowRadius: 2.5,
  },
};
