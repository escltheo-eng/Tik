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

import { Platform, type TextStyle } from 'react-native';

export const Cosmic = {
  bg: '#0a0c14',
  bgDeep: '#06070d',
  card: '#141a2b',
  cardAlt: '#1d2539',
  border: 'rgba(255,255,255,0.11)',
  borderStrong: 'rgba(255,255,255,0.18)',
  text: '#e8e4dc', // blanc crème chaud (choix maquettes) — doux pour les yeux sur OLED
  textDim: 'rgba(232,228,220,0.74)',
  textFaint: 'rgba(232,228,220,0.5)',
  accent: '#ffc15e', // ambre / safran (un peu plus lumineux pour le contraste)
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
export const TitleShadow: { strong: TextStyle; soft: TextStyle; glow: TextStyle } = {
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
  // Halo ambré pour les GROS titres (pages + héros) : donne un relief lumineux
  // « cosmique » plutôt qu'un simple texte blanc plat.
  glow: {
    textShadowColor: 'rgba(255,193,94,0.42)',
    textShadowOffset: { width: 0, height: 0 },
    textShadowRadius: 13,
  },
};

/**
 * Style de gros titre cosmique réutilisable (police serif système élégante +
 * léger interlettrage). À combiner avec `TitleShadow.glow` et une taille/poids.
 * `serifTitle` centralise le choix de police pour les titres de page/héros, le
 * temps que les vraies polices (Fraunces…) arrivent au bout 4.
 */
export const serifTitleFamily =
  Platform.select({ ios: 'ui-serif', web: "Georgia, 'Times New Roman', serif", default: 'serif' }) ??
  'serif';
