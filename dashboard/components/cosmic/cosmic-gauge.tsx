/**
 * CosmicGauge — jauge demi-cercle SVG générique (refonte γ, page Macro).
 *
 * Factorise la géométrie ÉPROUVÉE de `CosmicHitRate` (sweep-flag 1, viewBox
 * "0 0 200 92", arc 180°→360° par le HAUT — cf. bug sweep-flag corrigé le
 * 2026-06-19). `value` est normalisée sur [min, max] puis clampée [0,1]. Un
 * `markerValue` optionnel dessine un repère (ex : z=0 = moyenne 52 sem).
 * Le libellé central et la légende sont déjà formatés par l'appelant.
 *
 * Honnêteté (Axe #1) : la jauge ne sert qu'à VISUALISER un chiffre objectif déjà
 * mesuré (macro FRED / anticipation marché) — aucune prédiction de direction,
 * aucune précision inventée. CONTEXTE strict, comme les cartes qui l'utilisent.
 */

import { StyleSheet, Text, View } from 'react-native';
import Svg, { Line, Path } from 'react-native-svg';

import { Cosmic } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';

const CX = 100;
const CY = 84;
const R = 72;

function polar(deg: number, r: number = R): { x: number; y: number } {
  const a = (deg * Math.PI) / 180;
  return { x: CX + r * Math.cos(a), y: CY + r * Math.sin(a) };
}

/** Arc du demi-cercle HAUT (sweep 1 obligatoire — cf. CosmicHitRate). */
function arc(fromDeg: number, toDeg: number): string {
  const s = polar(fromDeg);
  const e = polar(toDeg);
  const large = Math.abs(toDeg - fromDeg) > 180 ? 1 : 0;
  return `M ${s.x} ${s.y} A ${R} ${R} 0 ${large} 1 ${e.x} ${e.y}`;
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x));
}

export interface CosmicGaugeProps {
  value: number;
  min: number;
  max: number;
  color: string;
  /** Texte central déjà formaté (ex : "+1.2σ", "68%"). */
  centerLabel: string;
  /** Légende sous la jauge (ex : "Liquidité en expansion"). */
  caption?: string;
  /** Valeur de référence à marquer d'un tick (ex : 0 = moyenne 52 sem). */
  markerValue?: number;
}

export function CosmicGauge({
  value,
  min,
  max,
  color,
  centerLabel,
  caption,
  markerValue,
}: CosmicGaugeProps) {
  const span = max - min;
  const frac = span > 0 ? clamp01((value - min) / span) : 0;
  const markerFrac =
    markerValue != null && span > 0 ? clamp01((markerValue - min) / span) : null;

  return (
    <View style={styles.wrap}>
      <Svg width={200} height={92} viewBox="0 0 200 92">
        {/* Track */}
        <Path
          d={arc(180, 360)}
          stroke="rgba(255,255,255,0.10)"
          strokeWidth={12}
          strokeLinecap="round"
          fill="none"
        />
        {/* Remplissage = valeur normalisée */}
        {frac > 0.001 ? (
          <Path
            d={arc(180, 180 + frac * 180)}
            stroke={color}
            strokeWidth={12}
            strokeLinecap="round"
            fill="none"
          />
        ) : null}
        {/* Repère de référence (ex : moyenne) */}
        {markerFrac != null ? (
          <Line
            x1={polar(180 + markerFrac * 180, R - 9).x}
            y1={polar(180 + markerFrac * 180, R - 9).y}
            x2={polar(180 + markerFrac * 180, R + 6).x}
            y2={polar(180 + markerFrac * 180, R + 6).y}
            stroke={Cosmic.text}
            strokeWidth={2.5}
          />
        ) : null}
      </Svg>
      <Text style={[styles.value, { color }]}>{centerLabel}</Text>
      {caption ? <Text style={styles.caption}>{caption}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    gap: 2,
    marginTop: 2,
  },
  value: {
    fontFamily: Fonts.mono,
    fontSize: 30,
    fontWeight: '800',
    marginTop: 2,
  },
  caption: {
    color: Cosmic.textDim,
    fontSize: 12,
    textAlign: 'center',
  },
});
