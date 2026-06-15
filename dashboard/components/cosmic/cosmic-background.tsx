/**
 * CosmicBackground — fond « cosmique pragmatique » (échantillon refonte γ).
 *
 * Dégradé radial bleu-nuit → noir profond + champ d'étoiles statiques, via
 * react-native-svg (DÉJÀ installé → zéro nouvelle dépendance). Pas d'animation
 * (perf mobile + sobriété). Les étoiles sont en positions fixes (pas de random)
 * pour un rendu stable d'un render à l'autre.
 */

import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Circle, Defs, RadialGradient, Rect, Stop } from 'react-native-svg';

import { Cosmic } from '@/constants/cosmic';

// Étoiles : x/y en % de l'écran, r en px, o = opacité. Réparties façon ciel.
const STARS: { x: number; y: number; r: number; o: number }[] = [
  { x: 6, y: 5, r: 1.1, o: 0.7 }, { x: 18, y: 11, r: 0.8, o: 0.5 },
  { x: 27, y: 4, r: 1.3, o: 0.8 }, { x: 39, y: 9, r: 0.7, o: 0.4 },
  { x: 52, y: 6, r: 1.0, o: 0.6 }, { x: 63, y: 12, r: 0.9, o: 0.5 },
  { x: 74, y: 5, r: 1.2, o: 0.75 }, { x: 86, y: 10, r: 0.8, o: 0.5 },
  { x: 94, y: 4, r: 1.0, o: 0.6 }, { x: 11, y: 22, r: 0.9, o: 0.5 },
  { x: 33, y: 26, r: 0.7, o: 0.4 }, { x: 48, y: 21, r: 1.1, o: 0.65 },
  { x: 69, y: 27, r: 0.8, o: 0.45 }, { x: 82, y: 23, r: 1.0, o: 0.6 },
  { x: 96, y: 28, r: 0.7, o: 0.4 }, { x: 4, y: 38, r: 1.0, o: 0.55 },
  { x: 22, y: 43, r: 0.8, o: 0.45 }, { x: 57, y: 40, r: 0.9, o: 0.5 },
  { x: 78, y: 45, r: 0.7, o: 0.4 }, { x: 90, y: 41, r: 1.1, o: 0.6 },
  { x: 14, y: 58, r: 0.8, o: 0.4 }, { x: 44, y: 62, r: 0.7, o: 0.35 },
  { x: 66, y: 57, r: 0.9, o: 0.45 }, { x: 88, y: 61, r: 0.7, o: 0.35 },
  { x: 8, y: 75, r: 0.9, o: 0.4 }, { x: 37, y: 79, r: 0.7, o: 0.3 },
  { x: 60, y: 74, r: 0.8, o: 0.38 }, { x: 83, y: 78, r: 0.7, o: 0.32 },
  { x: 20, y: 90, r: 0.8, o: 0.35 }, { x: 50, y: 93, r: 0.7, o: 0.3 },
  { x: 72, y: 89, r: 0.9, o: 0.4 }, { x: 95, y: 92, r: 0.7, o: 0.3 },
];

export function CosmicBackground({ children }: { children?: ReactNode }) {
  return (
    <View style={styles.root}>
      <Svg style={StyleSheet.absoluteFill} width="100%" height="100%">
        <Defs>
          <RadialGradient id="cosmicSky" cx="50%" cy="14%" r="95%">
            <Stop offset="0%" stopColor="#141d36" />
            <Stop offset="42%" stopColor={Cosmic.bg} />
            <Stop offset="100%" stopColor={Cosmic.bgDeep} />
          </RadialGradient>
        </Defs>
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#cosmicSky)" />
        {STARS.map((s, i) => (
          <Circle key={i} cx={`${s.x}%`} cy={`${s.y}%`} r={s.r} fill="#ffffff" opacity={s.o} />
        ))}
      </Svg>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: Cosmic.bgDeep,
  },
});
