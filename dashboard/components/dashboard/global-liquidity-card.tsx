/**
 * GlobalLiquidityCard — liquidité mondiale des banques centrales (ADR-028, CONTEXTE).
 *
 * Agrège les bilans Fed (WALCL) + ECB (ECBASSETSW) + BoJ (JPNASSETS), convertis en
 * USD, en une liquidité mondiale + son régime. C'est le driver macro structurel n°1
 * du BTC (« global liquidity → risk assets »). Données FRED gratuites, datées.
 *
 * ⚠ Contexte, PAS un signal Tik : ne touche jamais direction/veracity/combined_bias.
 * Le régime décrit un vent porteur/contraire HISTORIQUE, jamais une prédiction.
 */

import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { GlobalLiquidity } from '@/src/api/types';

export interface GlobalLiquidityCardProps {
  globalLiquidity: GlobalLiquidity | null;
  loading?: boolean;
  error?: string | null;
}

const GREEN = '#27ae60';
const WARN = '#e67e22';
const NEUTRAL = '#7f8c8d';
const FED = '#2980b9';
const ECB = '#16a085';
const BOJ = '#8e44ad';

function regimeLabel(r: string | null): string {
  switch (r) {
    case 'expansion':
      return 'En expansion';
    case 'contraction':
      return 'En contraction';
    case 'neutral':
      return 'Stable';
    default:
      return '—';
  }
}

function regimeColor(r: string | null): string {
  if (r === 'expansion') return GREEN;
  if (r === 'contraction') return WARN;
  return NEUTRAL;
}

function num(v: unknown): number | null {
  return typeof v === 'number' ? v : null;
}

export function GlobalLiquidityCard({ globalLiquidity, loading, error }: GlobalLiquidityCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];

  const gl = globalLiquidity;
  const hasData = gl?.available && gl.global_liquidity_tusd != null;
  const comp = (gl?.components ?? {}) as Record<string, unknown>;
  const fed = num(comp.fed_tusd);
  const ecb = num(comp.ecb_tusd);
  const boj = num(comp.boj_tusd);
  const total = (fed ?? 0) + (ecb ?? 0) + (boj ?? 0);

  const seg = (val: number | null, color: string) =>
    val != null && total > 0 ? (
      <View style={[styles.seg, { width: `${(val / total) * 100}%`, backgroundColor: color }]} />
    ) : null;

  const legendItem = (color: string, label: string, val: number | null) => (
    <ThemedView style={[styles.legendItem, { backgroundColor: 'transparent' }]}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <ThemedText style={styles.legendText}>
        {label} {val != null ? `${val.toFixed(2)} T$` : '—'}
      </ThemedText>
    </ThemedView>
  );

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Liquidité mondiale</ThemedText>
        <ThemedText style={styles.periodLabel}>Fed+ECB+BoJ · contexte</ThemedText>
      </ThemedView>

      <ThemedText style={styles.disclaimer}>
        Bilans des banques centrales convertis en USD — driver macro structurel du
        BTC, contexte (pas une prédiction).
      </ThemedText>

      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : loading && !gl ? (
        <ThemedText style={styles.emptyLabel}>Chargement…</ThemedText>
      ) : !hasData ? (
        <ThemedText style={styles.emptyLabel}>
          Aucune donnée collectée (l&apos;ingester n&apos;a pas encore publié).
        </ThemedText>
      ) : (
        <ThemedView style={[styles.body, { backgroundColor: 'transparent' }]}>
          <ThemedView style={[styles.headRow, { backgroundColor: 'transparent' }]}>
            <ThemedText style={styles.bigValue}>
              {gl!.global_liquidity_tusd!.toFixed(2)} T$
            </ThemedText>
            <View style={[styles.badge, { backgroundColor: regimeColor(gl!.regime) }]}>
              <ThemedText style={styles.badgeText}>{regimeLabel(gl!.regime)}</ThemedText>
            </View>
          </ThemedView>

          <ThemedText style={styles.subline}>
            Δ13 sem {gl!.delta_13w_busd != null ? `${gl!.delta_13w_busd >= 0 ? '+' : ''}${gl!.delta_13w_busd.toFixed(0)} Md$` : '—'}
            {gl!.zscore_52w != null ? ` · z ${gl!.zscore_52w.toFixed(2)}` : ''}
          </ThemedText>

          {total > 0 ? (
            <View style={styles.barTrack}>
              {seg(fed, FED)}
              {seg(ecb, ECB)}
              {seg(boj, BOJ)}
            </View>
          ) : null}

          <ThemedView style={[styles.legend, { backgroundColor: 'transparent' }]}>
            {legendItem(FED, 'Fed', fed)}
            {legendItem(ECB, 'ECB', ecb)}
            {legendItem(BOJ, 'BoJ', boj)}
          </ThemedView>

          {gl!.as_of ? (
            <ThemedText style={styles.asof}>Au {gl!.as_of}</ThemedText>
          ) : null}
        </ThemedView>
      )}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 10,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 4,
  },
  periodLabel: {
    fontSize: 12,
    opacity: 0.6,
  },
  disclaimer: {
    fontSize: 11,
    opacity: 0.6,
    fontStyle: 'italic',
  },
  body: {
    gap: 8,
  },
  headRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  bigValue: {
    fontSize: 20,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
  },
  badgeText: {
    color: '#fff',
    fontSize: 11,
    fontWeight: '600',
  },
  subline: {
    fontSize: 12,
    opacity: 0.75,
    fontVariant: ['tabular-nums'],
  },
  barTrack: {
    height: 10,
    borderRadius: 5,
    overflow: 'hidden',
    flexDirection: 'row',
    backgroundColor: 'rgba(127,140,141,0.2)',
  },
  seg: {
    height: '100%',
  },
  legend: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 14,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  legendText: {
    fontSize: 12,
    opacity: 0.8,
    fontVariant: ['tabular-nums'],
  },
  asof: {
    fontSize: 11,
    opacity: 0.5,
  },
  emptyLabel: {
    opacity: 0.6,
    paddingVertical: 8,
  },
  errorText: {
    color: '#c0392b',
    fontSize: 13,
  },
});
