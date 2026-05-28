/**
 * PersonalHitRateCard — Phase C Session 2 (Paquet 28).
 *
 * Affiche le hit rate "perso" calculé sur les entries watchlist résolues
 * avec verdict directionnel (confirmed + refuted), comparé au hit rate
 * Tik global équivalent (même horizon × entity dominant de la watchlist).
 *
 * Disclaimer biais de sélection si N résolus < 20 (cf. backlog #5 D5).
 */

import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import type { HitRate } from '@/src/api/types';
import {
  selectionBiasWarning,
  type PersonalHitRateStats,
} from '@/src/watchlist/stats';

export interface PersonalHitRateCardProps {
  stats: PersonalHitRateStats;
  /** Hit rate global Tik comparable (même horizon × entity dominant). */
  globalReference: HitRate | null;
  /** Label du contexte de comparaison (ex. "BTC swing — 30j"). */
  comparisonLabel: string | null;
  loading?: boolean;
  error?: string | null;
}

function colorForHitRate(rate: number | null): string {
  if (rate === null) return '#7f8c8d';
  if (rate >= 0.5) return '#27ae60';
  if (rate >= 0.3) return '#e67e22';
  return '#c0392b';
}

function formatHitRate(rate: number | null): string {
  if (rate === null) return '—';
  return `${(rate * 100).toFixed(0)}%`;
}

export function PersonalHitRateCard({
  stats,
  globalReference,
  comparisonLabel,
  loading,
  error,
}: PersonalHitRateCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];
  const personalColor = colorForHitRate(stats.hitRate);
  const warning = selectionBiasWarning(stats);

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <View style={styles.header}>
        <ThemedText type="defaultSemiBold">Hit rate perso</ThemedText>
        <ThemedText style={styles.subtitle}>
          sur tes signaux suivis résolus
        </ThemedText>
      </View>

      <View style={styles.mainRow}>
        <ThemedText type="title" style={[styles.percent, { color: personalColor }]}>
          {formatHitRate(stats.hitRate)}
        </ThemedText>
        <View style={styles.counterCol}>
          <ThemedText style={styles.counter}>
            {stats.confirmed} confirmé{stats.confirmed > 1 ? 's' : ''} / {stats.evaluable} évaluable{stats.evaluable > 1 ? 's' : ''}
          </ThemedText>
          <ThemedText style={styles.counterMuted}>
            ({stats.inconclusive} non concluant{stats.inconclusive > 1 ? 's' : ''} · {stats.na} sans verdict · {stats.pending} en attente)
          </ThemedText>
        </View>
      </View>

      {globalReference !== null && comparisonLabel !== null ? (
        <View style={[styles.compareRow, { borderTopColor: palette.icon }]}>
          {loading ? (
            <ActivityIndicator size="small" />
          ) : error ? (
            <ThemedText style={styles.errorText}>
              Référence Tik indisponible : {error}
            </ThemedText>
          ) : (
            <>
              <ThemedText style={styles.compareLabel}>
                Tik global {comparisonLabel}
              </ThemedText>
              <ThemedText
                style={[
                  styles.compareValue,
                  { color: colorForHitRate(globalReference.hit_rate) },
                ]}>
                {formatHitRate(globalReference.hit_rate)}{' '}
                <ThemedText style={styles.compareN}>
                  (n={globalReference.n_evaluated})
                </ThemedText>
              </ThemedText>
            </>
          )}
        </View>
      ) : null}

      {warning !== null ? (
        <View style={[styles.warningBox, { borderColor: '#e67e22' }]}>
          <ThemedText style={styles.warningText}>⚠ {warning}</ThemedText>
        </View>
      ) : null}

      {stats.manuallyResolvedCount > 0 ? (
        <ThemedText style={styles.metaNote}>
          {stats.manuallyResolvedCount} outcome{stats.manuallyResolvedCount > 1 ? 's' : ''} ajusté{stats.manuallyResolvedCount > 1 ? 's' : ''} manuellement
        </ThemedText>
      ) : null}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 10,
  },
  header: {
    gap: 2,
  },
  subtitle: {
    fontSize: 12,
    opacity: 0.65,
  },
  mainRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
  },
  percent: {
    fontSize: 34,
    lineHeight: 38,
    fontWeight: '700',
  },
  counterCol: {
    flex: 1,
    gap: 2,
  },
  counter: {
    fontSize: 13,
  },
  counterMuted: {
    fontSize: 11,
    opacity: 0.55,
  },
  compareRow: {
    borderTopWidth: 1,
    paddingTop: 8,
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    gap: 8,
  },
  compareLabel: {
    fontSize: 12,
    opacity: 0.7,
  },
  compareValue: {
    fontSize: 14,
    fontWeight: '600',
  },
  compareN: {
    fontSize: 11,
    fontWeight: '400',
    opacity: 0.6,
  },
  warningBox: {
    borderWidth: 1,
    borderRadius: 6,
    padding: 8,
  },
  warningText: {
    fontSize: 11,
    lineHeight: 15,
  },
  metaNote: {
    fontSize: 11,
    opacity: 0.6,
    fontStyle: 'italic',
  },
  errorText: {
    fontSize: 11,
    color: '#c0392b',
  },
});
