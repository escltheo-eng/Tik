/**
 * StatsLLMCard — taux de signaux portant une sortie LLM (vs fallback template).
 *
 * Refonte cosmique : View/Text + tokens Cosmic (rendue uniquement dans l'onglet
 * Plus, fond sombre forcé). Données 100 % réelles, zéro backend touché.
 */

import { StyleSheet, Text, View } from 'react-native';

import { Cosmic } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import { LlmStats } from '@/src/hooks/useDashboardKpis';
import { timeAgo } from '@/src/utils/time';

export interface StatsLLMCardProps {
  stats: LlmStats;
  loading?: boolean;
  error?: string | null;
}

function colorForPercent(percent: number | null): string {
  if (percent === null) return Cosmic.textFaint;
  if (percent >= 80) return Cosmic.long;
  if (percent >= 60) return Cosmic.neutral;
  return Cosmic.short;
}

export function StatsLLMCard({ stats, loading, error }: StatsLLMCardProps) {
  const color = colorForPercent(stats.percentOk);
  const percentLabel = stats.percentOk === null ? '—' : `${stats.percentOk.toFixed(0)}%`;
  const ok = stats.lastSignal?.isLlmOk ?? false;
  const badgeColor = ok ? Cosmic.long : Cosmic.neutral;

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Stats LLM</Text>
        <Text style={styles.periodLabel}>aujourd&apos;hui (00 h UTC)</Text>
      </View>

      {error ? (
        <Text style={styles.errorText}>Indisponible : {error}</Text>
      ) : stats.total === 0 ? (
        <Text style={styles.emptyLabel}>
          {loading ? 'Calcul en cours…' : 'Pas encore de signal aujourd’hui'}
        </Text>
      ) : (
        <>
          <View style={styles.percentRow}>
            <Text style={[styles.percent, { color }]}>{percentLabel}</Text>
            <Text style={styles.counter}>
              {stats.llmOk} / {stats.total} signaux avec sortie LLM
            </Text>
          </View>

          {stats.lastSignal ? (
            <View style={styles.lastRow}>
              <Text style={styles.lastLabel}>
                Dernier signal {timeAgo(stats.lastSignal.timestamp)}
              </Text>
              <View
                style={[
                  styles.badge,
                  { backgroundColor: badgeColor + '22', borderColor: badgeColor + '66' },
                ]}>
                <Text style={[styles.badgeLabel, { color: badgeColor }]}>
                  {ok ? 'LLM ✓' : 'fallback'}
                </Text>
              </View>
            </View>
          ) : null}
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
  title: {
    color: Cosmic.text,
    fontSize: 15,
    fontWeight: '700',
  },
  periodLabel: {
    color: Cosmic.textFaint,
    fontSize: 12,
    fontFamily: Fonts.mono,
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
    fontFamily: Fonts.mono,
  },
  counter: {
    color: Cosmic.textDim,
    fontSize: 13,
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
    color: Cosmic.textDim,
    fontSize: 12,
  },
  badge: {
    borderWidth: 1,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  badgeLabel: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  emptyLabel: {
    color: Cosmic.textDim,
    marginTop: 4,
  },
  errorText: {
    color: Cosmic.short,
    fontSize: 13,
  },
});
