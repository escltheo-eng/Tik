import { StyleSheet } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { LlmStats } from '@/src/hooks/useDashboardKpis';
import { timeAgo } from '@/src/utils/time';

export interface StatsLLMCardProps {
  stats: LlmStats;
  loading?: boolean;
  error?: string | null;
}

function colorForPercent(percent: number | null): string {
  if (percent === null) return '#7f8c8d';
  if (percent >= 80) return '#27ae60';
  if (percent >= 60) return '#e67e22';
  return '#c0392b';
}

export function StatsLLMCard({ stats, loading, error }: StatsLLMCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];
  const color = colorForPercent(stats.percentOk);
  const percentLabel =
    stats.percentOk === null ? '—' : `${stats.percentOk.toFixed(0)}%`;

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Stats LLM</ThemedText>
        <ThemedText style={styles.periodLabel}>aujourd&apos;hui (00 h UTC)</ThemedText>
      </ThemedView>

      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : stats.total === 0 ? (
        <ThemedText style={styles.emptyLabel}>
          {loading ? 'Calcul en cours…' : 'Pas encore de signal aujourd’hui'}
        </ThemedText>
      ) : (
        <>
          <ThemedView style={[styles.percentRow, { backgroundColor: 'transparent' }]}>
            <ThemedText type="title" style={[styles.percent, { color }]}>
              {percentLabel}
            </ThemedText>
            <ThemedText style={styles.counter}>
              {stats.llmOk} / {stats.total} signaux avec sortie LLM
            </ThemedText>
          </ThemedView>

          {stats.lastSignal ? (
            <ThemedView style={[styles.lastRow, { backgroundColor: 'transparent' }]}>
              <ThemedText style={styles.lastLabel}>
                Dernier signal {timeAgo(stats.lastSignal.timestamp)}
              </ThemedText>
              <ThemedView
                style={[
                  styles.badge,
                  {
                    backgroundColor: stats.lastSignal.isLlmOk ? '#27ae60' : '#7f8c8d',
                  },
                ]}>
                <ThemedText style={styles.badgeLabel}>
                  {stats.lastSignal.isLlmOk ? 'LLM ✓' : 'fallback'}
                </ThemedText>
              </ThemedView>
            </ThemedView>
          ) : null}
        </>
      )}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
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
  percentRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 12,
    flexWrap: 'wrap',
  },
  percent: {
    fontSize: 36,
    lineHeight: 40,
    fontWeight: '700',
  },
  counter: {
    fontSize: 13,
    opacity: 0.75,
  },
  lastRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 4,
    flexWrap: 'wrap',
    gap: 8,
  },
  lastLabel: {
    fontSize: 12,
    opacity: 0.7,
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
  },
  badgeLabel: {
    color: '#ffffff',
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 0.4,
  },
  emptyLabel: {
    opacity: 0.6,
    marginTop: 4,
  },
  errorText: {
    color: '#c0392b',
    fontSize: 13,
  },
});
