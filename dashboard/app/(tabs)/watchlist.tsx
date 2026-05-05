import { useRouter } from 'expo-router';
import { useMemo } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useTick } from '@/src/hooks/use-tick';
import { timeAgo } from '@/src/utils/time';
import { useWatchlist, type WatchlistEntry } from '@/src/watchlist/WatchlistContext';

const OUTCOME_LABELS: Record<WatchlistEntry['outcome'], string> = {
  pending: 'En attente',
  confirmed: 'Confirmé',
  refuted: 'Infirmé',
  n_a: 'N/A',
};

const OUTCOME_COLORS: Record<WatchlistEntry['outcome'], string> = {
  pending: '#7f8c8d',
  confirmed: '#27ae60',
  refuted: '#c0392b',
  n_a: '#95a5a6',
};

function directionColor(direction: string): string {
  switch (direction) {
    case 'long':
      return '#27ae60';
    case 'short':
      return '#c0392b';
    default:
      return '#7f8c8d';
  }
}

export default function WatchlistScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];
  const { entries, remove, clear, hydrated } = useWatchlist();
  useTick();

  const stats = useMemo(() => {
    const total = entries.length;
    const pending = entries.filter((e) => e.outcome === 'pending').length;
    const resolved = total - pending;
    return { total, pending, resolved };
  }, [entries]);

  const sortedEntries = useMemo(
    () => [...entries].sort((a, b) => b.addedAt.localeCompare(a.addedAt)),
    [entries],
  );

  const renderEntry = (entry: WatchlistEntry) => {
    const dirColor = directionColor(entry.direction);
    const outcomeColor = OUTCOME_COLORS[entry.outcome];
    return (
      <Pressable
        key={entry.signalId}
        onPress={() => router.push(`/signal/${encodeURIComponent(entry.signalId)}`)}
        style={({ pressed }) => [
          styles.row,
          {
            borderColor: palette.icon,
            backgroundColor: pressed
              ? colorScheme === 'dark'
                ? '#1a1d20'
                : '#f5f5f5'
              : 'transparent',
          },
        ]}>
        <View style={styles.rowHeader}>
          <ThemedText type="defaultSemiBold">{entry.entityId}</ThemedText>
          <View style={[styles.directionBadge, { backgroundColor: dirColor }]}>
            <ThemedText style={styles.directionLabel}>
              {entry.direction.toUpperCase()}
            </ThemedText>
          </View>
          <ThemedText style={styles.timestamp}>{timeAgo(entry.addedAt)}</ThemedText>
        </View>
        <View style={styles.metaLine}>
          <ThemedText style={styles.metaItem}>{entry.horizon}</ThemedText>
          <ThemedText style={styles.metaItem}>
            verac {(entry.veracity * 100).toFixed(0)}%
          </ThemedText>
          <ThemedText style={styles.metaItem}>
            conf {(entry.confidence * 100).toFixed(0)}%
          </ThemedText>
          <View style={[styles.outcomeBadge, { borderColor: outcomeColor }]}>
            <ThemedText style={[styles.outcomeLabel, { color: outcomeColor }]}>
              {OUTCOME_LABELS[entry.outcome]}
            </ThemedText>
          </View>
        </View>
        <Pressable
          onPress={() => remove(entry.signalId)}
          hitSlop={8}
          style={({ pressed }) => [styles.removeBtn, { opacity: pressed ? 0.4 : 0.7 }]}
          accessibilityRole="button"
          accessibilityLabel="Retirer de la watchlist">
          <ThemedText style={styles.removeBtnLabel}>×</ThemedText>
        </Pressable>
      </Pressable>
    );
  };

  return (
    <ThemedView style={[styles.container, { paddingTop: insets.top + 8 }]}>
      <View style={styles.header}>
        <ThemedText type="title">Watchlist</ThemedText>
        <ThemedText style={styles.subtitle}>
          Signaux marqués pour follow-up. L&apos;outcome (confirmé / infirmé) sera renseigné automatiquement à l&apos;expiration de l&apos;horizon dans une prochaine session.
        </ThemedText>
        {stats.total > 0 ? (
          <View style={styles.statsLine}>
            <ThemedText style={styles.statsItem}>
              <ThemedText type="defaultSemiBold">{stats.total}</ThemedText> suivi
              {stats.total > 1 ? 's' : ''}
            </ThemedText>
            <ThemedText style={styles.statsDot}>·</ThemedText>
            <ThemedText style={styles.statsItem}>
              {stats.pending} en attente
            </ThemedText>
            <ThemedText style={styles.statsDot}>·</ThemedText>
            <ThemedText style={styles.statsItem}>
              {stats.resolved} résolu{stats.resolved > 1 ? 's' : ''}
            </ThemedText>
          </View>
        ) : null}
        {stats.total > 0 ? (
          <View style={styles.actions}>
            <Pressable
              onPress={clear}
              style={({ pressed }) => [
                styles.actionBtn,
                { borderColor: palette.icon, opacity: pressed ? 0.6 : 1 },
              ]}>
              <ThemedText style={{ color: palette.text, fontSize: 13 }}>Tout effacer</ThemedText>
            </Pressable>
          </View>
        ) : null}
      </View>

      {!hydrated ? null : entries.length === 0 ? (
        <ThemedView style={styles.empty}>
          <ThemedText style={styles.emptyTitle}>Aucun signal suivi</ThemedText>
          <ThemedText style={styles.emptyText}>
            Ouvre un signal depuis l&apos;onglet Signals et tape sur ★ Suivre pour le marquer.
            Tu pourras ensuite suivre l&apos;évolution dans cet onglet et mesurer ton hit rate
            personnel.
          </ThemedText>
        </ThemedView>
      ) : (
        <ScrollView contentContainerStyle={styles.listContent}>
          {sortedEntries.map(renderEntry)}
        </ScrollView>
      )}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingHorizontal: 16,
  },
  header: {
    paddingBottom: 12,
    gap: 8,
  },
  subtitle: {
    fontSize: 13,
    opacity: 0.7,
  },
  statsLine: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 4,
  },
  statsItem: {
    fontSize: 13,
  },
  statsDot: {
    fontSize: 13,
    opacity: 0.5,
  },
  actions: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 4,
  },
  actionBtn: {
    borderWidth: 1,
    borderRadius: 16,
    paddingVertical: 6,
    paddingHorizontal: 12,
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
    gap: 12,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '600',
  },
  emptyText: {
    textAlign: 'center',
    opacity: 0.6,
    fontSize: 14,
    lineHeight: 20,
  },
  listContent: {
    paddingBottom: 24,
    gap: 8,
  },
  row: {
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    gap: 6,
    position: 'relative',
  },
  rowHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  directionBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
  },
  directionLabel: {
    color: '#ffffff',
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  timestamp: {
    fontSize: 11,
    opacity: 0.6,
    marginLeft: 'auto',
  },
  metaLine: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 8,
    marginTop: 2,
  },
  metaItem: {
    fontSize: 11,
    opacity: 0.7,
    textTransform: 'uppercase',
  },
  outcomeBadge: {
    borderWidth: 1,
    borderRadius: 4,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  outcomeLabel: {
    fontSize: 10,
    fontWeight: '600',
  },
  removeBtn: {
    position: 'absolute',
    top: 6,
    right: 8,
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  removeBtnLabel: {
    fontSize: 20,
    lineHeight: 22,
    fontWeight: '700',
  },
});
