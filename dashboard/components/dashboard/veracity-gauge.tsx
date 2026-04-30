import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';

const VERACITY_HIGH = 0.85;
const VERACITY_MEDIUM = 0.7;

function levelColor(value: number): string {
  if (value >= VERACITY_HIGH) return '#27ae60';
  if (value >= VERACITY_MEDIUM) return '#f39c12';
  return '#c0392b';
}

function levelLabel(value: number): string {
  if (value >= VERACITY_HIGH) return 'Concordance forte';
  if (value >= VERACITY_MEDIUM) return 'Concordance partielle';
  return 'Divergence';
}

export interface VeracityGaugeProps {
  value: number;
  status?: string;
}

export function VeracityGauge({ value, status }: VeracityGaugeProps) {
  const clamped = Math.max(0, Math.min(1, value));
  const pct = clamped * 100;
  const color = levelColor(clamped);
  const label = status ?? levelLabel(clamped);

  return (
    <View style={styles.container}>
      <View style={styles.headerRow}>
        <ThemedText type="defaultSemiBold">Veracity globale</ThemedText>
        <ThemedText style={[styles.percent, { color }]}>{pct.toFixed(0)}%</ThemedText>
      </View>
      <View style={styles.track}>
        <View style={[styles.bar, { width: `${pct}%`, backgroundColor: color }]} />
      </View>
      <ThemedText style={styles.statusLabel}>{label}</ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: 8,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  percent: {
    fontSize: 18,
    fontWeight: '700',
  },
  track: {
    height: 10,
    borderRadius: 5,
    backgroundColor: 'rgba(127, 140, 141, 0.2)',
    overflow: 'hidden',
  },
  bar: {
    height: '100%',
    borderRadius: 5,
  },
  statusLabel: {
    fontSize: 12,
    opacity: 0.7,
  },
});
