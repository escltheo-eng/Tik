/**
 * JournalStatsCard — bilan du carnet de trades + décomposition par alignement
 * Tik (with / against / none). Levier B (2026-06-03).
 *
 * C'est le « trésor » de la feature : il rend mesurable l'apport réel de Tik.
 * Tant que les N par groupe sont petits (< ~10), on affiche un avertissement
 * honnête « pas encore assez de trades pour conclure » — cohérent avec
 * l'exigence de rigueur de mesure du projet (go/no-go 2026-05-27).
 */

import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import type { ManualTradeGroupStats, ManualTradeStats } from '@/src/api/types';

const MIN_N_FOR_SIGNAL = 10;

function winPct(rate: number | null): string {
  if (rate === null) return '—';
  return `${(rate * 100).toFixed(0)}%`;
}

function signedPct(value: number | null): string {
  if (value === null || Number.isNaN(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function GroupRow({
  label,
  color,
  group,
}: {
  label: string;
  color: string;
  group: ManualTradeGroupStats;
}) {
  return (
    <View style={styles.groupRow}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <ThemedText style={styles.groupLabel}>{label}</ThemedText>
      <ThemedText style={styles.groupN}>({group.n})</ThemedText>
      <ThemedText style={styles.groupMetric}>
        {group.n > 0 ? `${winPct(group.win_rate)} · ${signedPct(group.avg_result_pct)}` : '—'}
      </ThemedText>
    </View>
  );
}

export function JournalStatsCard({ stats }: { stats: ManualTradeStats | null }) {
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];

  if (!stats || stats.n_closed === 0) {
    return (
      <View style={[styles.card, { borderColor: palette.icon }]}>
        <ThemedText type="defaultSemiBold">Bilan</ThemedText>
        <ThemedText style={styles.hint}>
          Aucun trade clôturé pour l&apos;instant. Le bilan « Tik t&apos;a-t-il aidée ? »
          apparaîtra dès que tu auras clôturé tes premiers trades.
        </ThemedText>
      </View>
    );
  }

  const a = stats.by_alignment;
  const enoughData =
    a.with.n >= MIN_N_FOR_SIGNAL || a.against.n >= MIN_N_FOR_SIGNAL;

  return (
    <View style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedText type="defaultSemiBold">Bilan</ThemedText>
      <ThemedText style={styles.overall}>
        {stats.n_closed} clôturés · {winPct(stats.win_rate)} gagnants ·{' '}
        {signedPct(stats.avg_result_pct)}/trade
      </ThemedText>
      {stats.n_open > 0 ? (
        <ThemedText style={styles.hint}>{stats.n_open} trade(s) en cours</ThemedText>
      ) : null}

      <ThemedText style={styles.section}>TIK T&apos;A-T-IL AIDÉE ?</ThemedText>
      <GroupRow label="Avec Tik" color="#27ae60" group={a.with} />
      <GroupRow label="Contre Tik" color="#c0392b" group={a.against} />
      <GroupRow label="Sans signal" color="#7f8c8d" group={a.none} />

      <ThemedText style={styles.caveat}>
        {enoughData
          ? 'Lecture indicative : compare le « avec » au « contre ». Reste prudente tant que les N par groupe sont modestes.'
          : `Pas encore assez de trades clôturés pour conclure (vise ≥ ${MIN_N_FOR_SIGNAL} par groupe). On mesure, on ne parie pas.`}
      </ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 10,
    padding: 14,
    gap: 6,
  },
  overall: {
    fontSize: 14,
    fontWeight: '600',
  },
  hint: {
    fontSize: 12,
    opacity: 0.6,
  },
  section: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.4,
    opacity: 0.7,
    marginTop: 6,
  },
  groupRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  dot: {
    width: 9,
    height: 9,
    borderRadius: 5,
  },
  groupLabel: {
    fontSize: 13,
    minWidth: 88,
  },
  groupN: {
    fontSize: 12,
    opacity: 0.6,
  },
  groupMetric: {
    fontSize: 13,
    fontWeight: '600',
    marginLeft: 'auto',
  },
  caveat: {
    fontSize: 11,
    opacity: 0.55,
    lineHeight: 16,
    marginTop: 6,
    fontStyle: 'italic',
  },
});
