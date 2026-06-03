/**
 * DerivativesCard — positionnement dérivés Binance BTC (SHADOW — contexte).
 *
 * Affiche le funding rate, l'open interest et le positionnement long/short
 * (comptes retail vs top traders « smart money »), adossés à de l'argent réel +
 * du levier. Famille de données DIFFÉRENTE du sentiment retardé (ADR-023).
 *
 * ⚠ Contexte, PAS un signal Tik : ces données ne sont branchées sur aucun
 * signal (shadow strict). À lire à côté de son jugement. Lecture utile :
 * - funding très positif = longs encombrés → risque de squeeze (prudence) ;
 * - retail très long alors que les top traders ne le sont pas = divergence,
 *   souvent un avertissement contrarian.
 */

import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { DerivativesSnapshot } from '@/src/api/types';

export interface DerivativesCardProps {
  snapshot: DerivativesSnapshot | null;
  loading?: boolean;
  error?: string | null;
}

const WARN = '#e67e22';
const DIVERGENCE_FRAC = 0.05;

function fundingPct(snap: DerivativesSnapshot): number | null {
  return snap.funding_rate != null ? snap.funding_rate * 100 : null;
}

function fundingLabel(pct: number | null): string {
  if (pct == null) return '—';
  const a = Math.abs(pct);
  if (a < 0.01) return 'neutre';
  const side = pct > 0 ? 'longs paient' : 'shorts paient';
  return a >= 0.05 ? `${side}, élevé` : side;
}

function formatOiUsd(usd: number | null): string {
  if (usd == null || usd <= 0) return '—';
  if (usd >= 1e9) return `${(usd / 1e9).toFixed(1)} Mds$`;
  if (usd >= 1e6) return `${(usd / 1e6).toFixed(0)} M$`;
  return `${Math.round(usd)}$`;
}

/** Part de longs en % depuis le compte (fraction) ou, à défaut, le ratio L/S. */
function longPct(account: number | null, ratio: number | null): number | null {
  if (account != null) return account * 100;
  if (ratio != null && ratio >= 0) return (ratio / (1 + ratio)) * 100;
  return null;
}

export function DerivativesCard({ snapshot, loading, error }: DerivativesCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];

  const hasData = snapshot != null && snapshot.fetched_at != null;
  const pct = snapshot ? fundingPct(snapshot) : null;
  const fundingExtreme = pct != null && Math.abs(pct) >= 0.05;
  const retailLong = snapshot
    ? longPct(snapshot.long_account_global, snapshot.long_short_ratio_global)
    : null;
  const topLong = snapshot
    ? longPct(snapshot.long_account_top, snapshot.long_short_ratio_top)
    : null;
  const divergent =
    retailLong != null && topLong != null
      ? Math.abs(retailLong - topLong) >= DIVERGENCE_FRAC * 100
      : null;

  const renderLongRow = (label: string, value: number | null) => (
    <ThemedView style={[styles.row, { backgroundColor: 'transparent' }]}>
      <ThemedText style={styles.rowLabel}>{label}</ThemedText>
      <View style={[styles.barTrack, { backgroundColor: palette.icon }]}>
        <View
          style={[
            styles.barFill,
            { width: `${Math.max(2, Math.min(100, value ?? 0))}%` },
          ]}
        />
      </View>
      <ThemedText style={styles.rowValue}>
        {value != null ? `${value.toFixed(0)}% longs` : '—'}
      </ThemedText>
    </ThemedView>
  );

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Positionnement dérivés BTC</ThemedText>
        <ThemedText style={styles.periodLabel}>shadow · contexte</ThemedText>
      </ThemedView>

      <ThemedText style={styles.disclaimer}>
        Données Binance (argent réel + levier) — contexte, pas un signal Tik.
      </ThemedText>

      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : loading && !snapshot ? (
        <ThemedText style={styles.emptyLabel}>Chargement…</ThemedText>
      ) : !hasData ? (
        <ThemedText style={styles.emptyLabel}>
          Aucune donnée collectée (l&apos;ingester n&apos;a pas encore publié).
        </ThemedText>
      ) : (
        <ThemedView style={[styles.body, { backgroundColor: 'transparent' }]}>
          <ThemedView style={[styles.metricRow, { backgroundColor: 'transparent' }]}>
            <ThemedText style={styles.metricLabel}>Funding (8h)</ThemedText>
            <ThemedText
              style={[styles.metricValue, fundingExtreme ? { color: WARN } : null]}>
              {pct != null ? `${pct >= 0 ? '+' : ''}${pct.toFixed(3)}%` : '—'}
              <ThemedText style={styles.metricNote}> · {fundingLabel(pct)}</ThemedText>
            </ThemedText>
          </ThemedView>

          <ThemedView style={[styles.metricRow, { backgroundColor: 'transparent' }]}>
            <ThemedText style={styles.metricLabel}>Open interest</ThemedText>
            <ThemedText style={styles.metricValue}>
              {formatOiUsd(snapshot!.open_interest_usd)}
            </ThemedText>
          </ThemedView>

          {renderLongRow('Retail', retailLong)}
          {renderLongRow('Top traders', topLong)}

          {divergent != null ? (
            <ThemedText
              style={[styles.interpretation, divergent ? { color: WARN } : null]}>
              {divergent
                ? '⚠ Retail et top traders divergent — souvent un signal contrarian'
                : 'Retail et top traders alignés — pas de divergence'}
            </ThemedText>
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
  metricRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  metricLabel: {
    fontSize: 13,
    opacity: 0.8,
  },
  metricValue: {
    fontSize: 14,
    fontWeight: '600',
    fontVariant: ['tabular-nums'],
  },
  metricNote: {
    fontSize: 12,
    fontWeight: '400',
    opacity: 0.7,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  rowLabel: {
    fontSize: 12,
    width: 84,
    opacity: 0.8,
  },
  barTrack: {
    flex: 1,
    height: 6,
    borderRadius: 3,
    overflow: 'hidden',
    opacity: 0.3,
  },
  barFill: {
    height: '100%',
    backgroundColor: '#2980b9',
    borderRadius: 3,
  },
  rowValue: {
    fontSize: 12,
    width: 72,
    textAlign: 'right',
    fontVariant: ['tabular-nums'],
  },
  emptyLabel: {
    opacity: 0.6,
    paddingVertical: 8,
  },
  errorText: {
    color: '#c0392b',
    fontSize: 13,
  },
  interpretation: {
    fontSize: 12,
    marginTop: 2,
    opacity: 0.85,
  },
});
