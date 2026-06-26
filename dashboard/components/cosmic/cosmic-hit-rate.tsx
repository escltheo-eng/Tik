/**
 * CosmicHitRate — hit-rate en JAUGE demi-cercle vs baseline (refonte γ, bout 6).
 *
 * Demi-cercle SVG : remplissage = hit-rate mesuré, repère = baseline « robot bête »
 * (anti-surconfiance) → on voit d'un coup si Tik fait mieux. Sélecteurs actif /
 * horizon. Remplace la carte thémée `HitRateCard`. Données réelles (HitRate).
 *
 * Honnêteté (Axe #1) : mesure observée, pas une garantie d'edge (NO-GO 2026-05-27).
 */

import { Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Line, Path } from 'react-native-svg';

import { UnavailableState } from './cosmic-unavailable-state';

import { Cosmic } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import type { HitRate } from '@/src/api/types';

interface Props {
  data: HitRate | null;
  entityId: string;
  horizon: string;
  onEntityChange?: (e: string) => void;
  onHorizonChange?: (h: string) => void;
  loading?: boolean;
  error?: string | null;
}

const ENTITIES = ['BTC', 'GOLD'] as const;
const HORIZONS = ['flash', 'swing', 'macro'] as const;

const CX = 100;
const CY = 84;
const R = 72;

function polar(deg: number, r: number = R): { x: number; y: number } {
  const a = (deg * Math.PI) / 180;
  return { x: CX + r * Math.cos(a), y: CY + r * Math.sin(a) };
}

/**
 * Arc du demi-cercle HAUT : 180° (gauche) → 360° (droite) via 270° (haut).
 *
 * sweep-flag = 1 (et NON 0) : en SVG (y vers le bas), un parcours gauche→droite
 * PAR LE HAUT est horaire à l'écran → sweep 1. Avec sweep 0 l'arc passait par le
 * bas (milieu en y=156, hors du viewBox de 92 → demi-cercle « mal affiché »), et
 * le remplissage tombait même sur un autre cercle. Vérifié par la paramétrisation
 * centre de la spec SVG (track milieu y=12 = haut ; remplissage centré sur (100,84)).
 */
function arc(fromDeg: number, toDeg: number): string {
  const s = polar(fromDeg);
  const e = polar(toDeg);
  const large = Math.abs(toDeg - fromDeg) > 180 ? 1 : 0;
  return `M ${s.x} ${s.y} A ${R} ${R} 0 ${large} 1 ${e.x} ${e.y}`;
}

function hitColor(rate: number): string {
  if (rate >= 0.6) return Cosmic.long;
  if (rate >= 0.45) return Cosmic.neutral;
  return Cosmic.short;
}

export function CosmicHitRate({
  data,
  entityId,
  horizon,
  onEntityChange,
  onHorizonChange,
  loading,
  error,
}: Props) {
  const hr = data ? Math.max(0, Math.min(1, data.hit_rate)) : null;
  const baseline = data?.best_baseline_hit_rate ?? null;

  const pill = (label: string, active: boolean, onPress?: () => void) => (
    <Pressable
      key={label}
      onPress={onPress}
      style={[styles.pill, active ? styles.pillActive : null]}>
      <Text style={[styles.pillText, active ? styles.pillTextActive : null]}>{label}</Text>
    </Pressable>
  );

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Hit-rate vs baseline</Text>
      </View>

      <View style={styles.selectors}>
        {ENTITIES.map((e) => pill(e, entityId === e, () => onEntityChange?.(e)))}
        <View style={styles.sep} />
        {HORIZONS.map((h) => pill(h, horizon === h, () => onHorizonChange?.(h)))}
      </View>

      {error ? (
        <UnavailableState kind="error" error={error} />
      ) : loading && !data ? (
        <UnavailableState kind="loading" />
      ) : hr == null ? (
        <UnavailableState kind="empty" message="Pas encore de mesure pour ce couple actif / horizon." />
      ) : (
        <>
          <View style={styles.gaugeWrap}>
            <Svg width={200} height={92} viewBox="0 0 200 92">
              {/* Track */}
              <Path d={arc(180, 360)} stroke="rgba(255,255,255,0.10)" strokeWidth={12} strokeLinecap="round" fill="none" />
              {/* Remplissage = hit-rate */}
              <Path
                d={arc(180, 180 + hr * 180)}
                stroke={hitColor(hr)}
                strokeWidth={12}
                strokeLinecap="round"
                fill="none"
              />
              {/* Repère baseline */}
              {baseline != null ? (
                <Line
                  x1={polar(180 + baseline * 180, R - 9).x}
                  y1={polar(180 + baseline * 180, R - 9).y}
                  x2={polar(180 + baseline * 180, R + 6).x}
                  y2={polar(180 + baseline * 180, R + 6).y}
                  stroke={Cosmic.text}
                  strokeWidth={2.5}
                />
              ) : null}
            </Svg>
            <Text style={[styles.gaugeValue, { color: hitColor(hr) }]}>{(hr * 100).toFixed(0)}%</Text>
            <Text style={styles.gaugeSub}>{data!.n_evaluated} mesurés</Text>
          </View>

          <View style={styles.baselineRow}>
            <Text style={styles.baselineText}>
              {baseline != null
                ? `Baseline « ${data!.best_baseline_label ?? '—'} » : ${(baseline * 100).toFixed(0)}%`
                : 'Baseline indisponible'}
            </Text>
            {data!.beats_baseline != null ? (
              <Text
                style={[
                  styles.beats,
                  { color: data!.beats_baseline ? Cosmic.long : Cosmic.short },
                ]}>
                {data!.beats_baseline ? '✓ bat la baseline' : '✗ ne bat pas'}
              </Text>
            ) : null}
          </View>

          <Text style={styles.caveat}>
            {`Gain moy. ${data!.avg_gain_pct >= 0 ? '+' : ''}${data!.avg_gain_pct.toFixed(2)}% · mesure observée, pas une garantie d'edge (NO-GO).`}
          </Text>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
    gap: 12,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  title: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  selectors: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 6,
  },
  sep: { width: 8 },
  pill: {
    paddingHorizontal: 11,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: Cosmic.borderStrong,
  },
  pillActive: { backgroundColor: Cosmic.accent, borderColor: Cosmic.accent },
  pillText: { color: Cosmic.textDim, fontSize: 12, fontWeight: '700' },
  pillTextActive: { color: Cosmic.bgDeep },
  gaugeWrap: {
    alignItems: 'center',
    gap: 2,
    marginTop: 2,
  },
  gaugeValue: {
    fontFamily: Fonts.mono,
    fontSize: 34,
    fontWeight: '800',
    marginTop: 2,
  },
  gaugeSub: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontFamily: Fonts.mono,
  },
  baselineRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
  },
  baselineText: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontFamily: Fonts.mono,
  },
  beats: {
    fontSize: 12,
    fontWeight: '800',
  },
  caveat: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontStyle: 'italic',
    lineHeight: 15,
  },
  empty: {
    color: Cosmic.textDim,
    fontSize: 13,
    paddingVertical: 8,
  },
});
