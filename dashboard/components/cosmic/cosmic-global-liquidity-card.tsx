/**
 * CosmicGlobalLiquidityCard — port cosmique de `GlobalLiquidityCard` (ADR-028).
 *
 * Liquidité mondiale Fed+ECB+BoJ (convertie USD) + régime + barre de composition.
 * Mêmes données (prop `globalLiquidity`) que la carte thémée, rendu palette γ.
 * CONTEXTE STRICT : ne touche jamais direction/veracity/combined_bias.
 */

import { StyleSheet, Text, View } from 'react-native';

import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import type { GlobalLiquidity } from '@/src/api/types';

export interface CosmicGlobalLiquidityCardProps {
  globalLiquidity: GlobalLiquidity | null;
  loading?: boolean;
  error?: string | null;
}

const REGIME_BG: Record<string, string> = {
  expansion: '#3fae86',
  contraction: '#d99a3c',
  neutral: '#6b7280',
};
const FED = '#4a9fd8';
const ECB = '#1ec9a8';
const BOJ = '#a974d8';

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

function regimeBg(r: string | null): string {
  return REGIME_BG[r ?? ''] ?? '#6b7280';
}

function num(v: unknown): number | null {
  return typeof v === 'number' ? v : null;
}

export function CosmicGlobalLiquidityCard({
  globalLiquidity,
  loading,
  error,
}: CosmicGlobalLiquidityCardProps) {
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
    <View style={styles.legendItem}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={styles.legendText}>
        {label} {val != null ? `${val.toFixed(2)} T$` : '—'}
      </Text>
    </View>
  );

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Liquidité mondiale</Text>
        <Text style={styles.periodLabel}>Fed+ECB+BoJ · contexte</Text>
      </View>

      <Text style={styles.disclaimer}>
        Bilans des banques centrales convertis en USD — driver macro structurel du BTC, contexte
        (pas une prédiction).
      </Text>

      {error ? (
        <Text style={styles.errorText}>Indisponible : {error}</Text>
      ) : loading && !gl ? (
        <Text style={styles.emptyLabel}>Chargement…</Text>
      ) : !hasData ? (
        <Text style={styles.emptyLabel}>
          {"Aucune donnée collectée (l'ingester n'a pas encore publié)."}
        </Text>
      ) : (
        <View style={styles.body}>
          <View style={styles.headRow}>
            <Text style={styles.bigValue}>{gl!.global_liquidity_tusd!.toFixed(2)} T$</Text>
            <View style={[styles.badge, { backgroundColor: regimeBg(gl!.regime) }]}>
              <Text style={styles.badgeText}>{regimeLabel(gl!.regime)}</Text>
            </View>
          </View>

          <Text style={styles.subline}>
            Δ13 sem{' '}
            {gl!.delta_13w_busd != null
              ? `${gl!.delta_13w_busd >= 0 ? '+' : ''}${gl!.delta_13w_busd.toFixed(0)} Md$`
              : '—'}
            {gl!.zscore_52w != null ? ` · z ${gl!.zscore_52w.toFixed(2)}` : ''}
          </Text>

          {total > 0 ? (
            <View style={styles.barTrack}>
              {seg(fed, FED)}
              {seg(ecb, ECB)}
              {seg(boj, BOJ)}
            </View>
          ) : null}

          <View style={styles.legend}>
            {legendItem(FED, 'Fed', fed)}
            {legendItem(ECB, 'ECB', ecb)}
            {legendItem(BOJ, 'BoJ', boj)}
          </View>

          {gl!.as_of ? <Text style={styles.asof}>Au {gl!.as_of}</Text> : null}
        </View>
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
  title: {
    ...TitleShadow.soft,
    fontFamily: serifTitleFamily,
    color: Cosmic.text,
    fontSize: 16,
    fontWeight: '700',
  },
  periodLabel: {
    color: Cosmic.textFaint,
    fontSize: 12,
  },
  disclaimer: {
    color: Cosmic.textFaint,
    fontSize: 11,
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
    color: Cosmic.text,
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
    color: '#ffffff',
    fontSize: 11,
    fontWeight: '600',
  },
  subline: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontVariant: ['tabular-nums'],
  },
  barTrack: {
    height: 10,
    borderRadius: 5,
    overflow: 'hidden',
    flexDirection: 'row',
    backgroundColor: 'rgba(255,255,255,0.08)',
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
    color: Cosmic.textDim,
    fontSize: 12,
    fontVariant: ['tabular-nums'],
  },
  asof: {
    color: Cosmic.textFaint,
    fontSize: 11,
  },
  emptyLabel: {
    color: Cosmic.textDim,
    fontSize: 13,
    paddingVertical: 8,
  },
  errorText: {
    color: Cosmic.short,
    fontSize: 13,
  },
});
