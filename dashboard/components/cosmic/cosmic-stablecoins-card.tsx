/**
 * CosmicStablecoinsCard — masse de stablecoins + tendance (ADR-031, CONTEXTE strict).
 *
 * La « poudre sèche » crypto-native : le cash en USD parqué sur les rails on-chain
 * (USDT, USDC, …), via DefiLlama (gratuit). Masse qui monte = capital qui entre
 * (potentiel d'achat) ; qui descend = sorties. Jauge z-score (vs moyenne 90 j) +
 * total + Δ + répartition des principaux stablecoins.
 *
 * Honnêteté (Axe #1 / ADR-031) : ces chiffres datés ne touchent JAMAIS
 * direction/veracity/combined_bias. `trend` décrit le sens du flux de capital, PAS
 * une prédiction du prix BTC (la liquidité ne prédit pas le BTC, mesuré 2026-06-19).
 */

import { StyleSheet, Text, View } from 'react-native';

import { UnavailableState } from './cosmic-unavailable-state';

import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import type { Stablecoins } from '@/src/api/types';
import { useTick } from '@/src/hooks/use-tick';
import { timeAgo } from '@/src/utils/time';

import { CosmicGauge } from './cosmic-gauge';

export interface CosmicStablecoinsCardProps {
  stablecoins: Stablecoins | null;
  loading?: boolean;
  error?: string | null;
}

// Mêmes couleurs que la carte liquidité (expansion vert / contraction ambre /
// neutre gris) — visualise un chiffre objectif, sans impliquer « acheter/vendre ».
const TREND_BG: Record<string, string> = {
  expansion: '#3fae86',
  contraction: '#d99a3c',
  neutral: '#6b7280',
};

function trendLabel(t: string | null): string {
  switch (t) {
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

function trendBg(t: string | null): string {
  return TREND_BG[t ?? ''] ?? '#6b7280';
}

function fmtDelta(busd: number | null): string {
  if (busd == null) return '—';
  return `${busd >= 0 ? '+' : ''}${busd.toFixed(1)} Md$`;
}

export function CosmicStablecoinsCard({ stablecoins, loading, error }: CosmicStablecoinsCardProps) {
  useTick(); // fraîcheur « il y a X » rafraîchie en temps réel
  const sc = stablecoins;
  const hasData = sc?.available && sc?.total_busd != null;

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Stablecoins</Text>
        <Text style={styles.periodLabel}>DefiLlama · contexte</Text>
      </View>

      <Text style={styles.disclaimer}>
        La « poudre sèche » crypto : le cash en USD parqué sur les rails on-chain — contexte, pas un
        signal Tik.
      </Text>

      {error ? (
        <UnavailableState kind="error" error={error} />
      ) : loading && !sc ? (
        <UnavailableState kind="loading" />
      ) : !hasData ? (
        <UnavailableState
          kind="empty"
          message="Aucune donnée collectée (l'ingester n'a pas encore publié)."
        />
      ) : (
        <View style={styles.body}>
          {/* Jauge headline : z-score 90 j de la masse (contraction ↔ expansion) */}
          {sc!.zscore_90d != null ? (
            <CosmicGauge
              value={sc!.zscore_90d}
              min={-2.5}
              max={2.5}
              markerValue={0}
              color={trendBg(sc!.trend)}
              centerLabel={`${sc!.zscore_90d >= 0 ? '+' : ''}${sc!.zscore_90d.toFixed(1)}σ`}
              caption={`${trendLabel(sc!.trend)} · vs moyenne 90 j`}
            />
          ) : null}

          {/* Masse totale — bloc mis en avant */}
          <View style={styles.totalBlock}>
            <View style={styles.totalHead}>
              <Text style={styles.totalTitle}>Masse totale</Text>
              <View style={[styles.badge, { backgroundColor: trendBg(sc!.trend) }]}>
                <Text style={styles.badgeText}>{trendLabel(sc!.trend)}</Text>
              </View>
            </View>
            <Text style={styles.totalValue}>
              {sc!.total_busd!.toFixed(0)} Md$
              <Text style={styles.metricNote}>
                {'  '}Δ30 j {fmtDelta(sc!.delta_30d_busd)}
                {sc!.pct_30d != null ? ` (${sc!.pct_30d >= 0 ? '+' : ''}${sc!.pct_30d}%)` : ''}
              </Text>
            </Text>
            <Text style={styles.interpretation}>
              Masse en hausse = du capital entre sur les rails crypto (potentiel d&apos;achat) ; en
              baisse = des sorties. Contexte, pas une prédiction.
            </Text>
          </View>

          {sc!.delta_7d_busd != null ? (
            <View style={styles.metricRow}>
              <Text style={styles.metricLabel}>Variation 7 j</Text>
              <Text style={styles.metricValue}>{fmtDelta(sc!.delta_7d_busd)}</Text>
            </View>
          ) : null}

          {/* Répartition des principaux stablecoins (concentration) */}
          {sc!.breakdown.length > 0 ? (
            <View style={styles.breakdownBlock}>
              <Text style={styles.breakdownTitle}>Principaux stablecoins</Text>
              {sc!.breakdown.slice(0, 5).map((b) => {
                const share = b.share ?? 0;
                return (
                  <View key={b.symbol ?? b.name ?? Math.random().toString()} style={styles.barRow}>
                    <Text style={styles.barLabel} numberOfLines={1}>
                      {b.symbol ?? b.name ?? '—'}
                    </Text>
                    <View style={styles.barTrack}>
                      <View
                        style={[styles.barFill, { width: `${Math.min(100, share * 100)}%` }]}
                      />
                    </View>
                    <Text style={styles.barPct}>{Math.round(share * 100)}%</Text>
                  </View>
                );
              })}
            </View>
          ) : null}

          {sc!.as_of ? (
            <Text style={styles.asof}>
              Données au {sc!.as_of} · il y a {timeAgo(sc!.as_of)}
            </Text>
          ) : null}
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
  periodLabel: { color: Cosmic.textFaint, fontSize: 12 },
  disclaimer: { color: Cosmic.textFaint, fontSize: 11, fontStyle: 'italic' },
  body: { gap: 8 },
  totalBlock: { gap: 4, paddingBottom: 6 },
  totalHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  totalTitle: { color: Cosmic.textDim, fontSize: 13 },
  totalValue: {
    color: Cosmic.text,
    fontSize: 18,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  badge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 10 },
  badgeText: { color: '#ffffff', fontSize: 11, fontWeight: '600' },
  metricRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  metricLabel: { color: Cosmic.textDim, fontSize: 13 },
  metricValue: {
    color: Cosmic.text,
    fontSize: 14,
    fontWeight: '600',
    fontVariant: ['tabular-nums'],
  },
  metricNote: { color: Cosmic.textFaint, fontSize: 12, fontWeight: '400' },
  interpretation: { color: Cosmic.textDim, fontSize: 12, lineHeight: 17 },
  breakdownBlock: { gap: 5, marginTop: 2 },
  breakdownTitle: { color: Cosmic.textDim, fontSize: 13, marginBottom: 1 },
  barRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  barLabel: {
    color: Cosmic.text,
    fontSize: 12,
    fontWeight: '600',
    width: 52,
    fontVariant: ['tabular-nums'],
  },
  barTrack: {
    flex: 1,
    height: 8,
    borderRadius: 4,
    backgroundColor: 'rgba(255,255,255,0.07)',
    overflow: 'hidden',
  },
  barFill: {
    height: 8,
    borderRadius: 4,
    backgroundColor: Cosmic.macro,
  },
  barPct: {
    color: Cosmic.textDim,
    fontSize: 11,
    width: 34,
    textAlign: 'right',
    fontVariant: ['tabular-nums'],
  },
  asof: { color: Cosmic.textFaint, fontSize: 11, marginTop: 2 },
  emptyLabel: { color: Cosmic.textDim, fontSize: 13, paddingVertical: 8 },
  errorText: { color: Cosmic.short, fontSize: 13 },
});
