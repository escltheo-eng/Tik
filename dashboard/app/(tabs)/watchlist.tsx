import { useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { PersonalHitRateCard } from '@/components/watchlist/personal-hit-rate-card';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { getHitRate, reportFeedback } from '@/src/api/endpoints';
import type { HitRate } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';
import { useTick } from '@/src/hooks/use-tick';
import { timeAgo } from '@/src/utils/time';
import {
  formatExitReason,
  formatTradeId,
  mapOutcomeToFeedback,
} from '@/src/watchlist/outcome';
import {
  computePersonalStats,
  dominantEntity,
  dominantHorizon,
} from '@/src/watchlist/stats';
import { useAutoResolveWatchlist } from '@/src/watchlist/useAutoResolveWatchlist';
import {
  useWatchlist,
  type WatchlistEntry,
  type WatchlistOutcome,
} from '@/src/watchlist/WatchlistContext';

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
  const { entries, remove, setOutcome, clear, hydrated } = useWatchlist();
  const { client, isAuthenticated } = useAuth();
  useTick();

  // Hook auto-resolution (Phase C Session 2). Cycle au boot + interval 5 min.
  useAutoResolveWatchlist(client, isAuthenticated);

  const personalStats = useMemo(() => computePersonalStats(entries), [entries]);

  // Référence Tik global comparable (horizon × entity dominant de la watchlist).
  const [globalRef, setGlobalRef] = useState<HitRate | null>(null);
  const [globalLoading, setGlobalLoading] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);

  const comparison = useMemo(() => {
    const h = dominantHorizon(entries);
    const e = dominantEntity(entries);
    if (!h || !e) return null;
    return {
      horizon: h,
      entity: e,
      label: `${e} ${h} — 30j`,
    };
  }, [entries]);

  useEffect(() => {
    if (!comparison || !isAuthenticated) {
      setGlobalRef(null);
      return;
    }
    let cancelled = false;
    setGlobalLoading(true);
    setGlobalError(null);
    getHitRate(client, comparison.entity, comparison.horizon, {
      sinceDays: 30,
      includeFlagged: false,
    })
      .then((res) => {
        if (!cancelled) setGlobalRef(res);
      })
      .catch((err) => {
        if (!cancelled) setGlobalError((err as Error).message ?? 'erreur');
      })
      .finally(() => {
        if (!cancelled) setGlobalLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client, isAuthenticated, comparison]);

  const sortedEntries = useMemo(
    () => [...entries].sort((a, b) => b.addedAt.localeCompare(a.addedAt)),
    [entries],
  );

  const confirmRemove = (entry: WatchlistEntry) => {
    Alert.alert(
      'Retirer de la watchlist ?',
      `${entry.entityId} · ${entry.direction.toUpperCase()} · ${entry.horizon}`,
      [
        { text: 'Annuler', style: 'cancel' },
        {
          text: 'Retirer',
          style: 'destructive',
          onPress: () => remove(entry.signalId),
        },
      ],
    );
  };

  const openOverrideModal = useCallback(
    (entry: WatchlistEntry) => {
      const applyOverride = (chosen: WatchlistOutcome) => {
        setOutcome(entry.signalId, chosen, null);
        // Fire-and-forget POST /feedback côté backend.
        const feedbackOutcome = mapOutcomeToFeedback(chosen);
        if (feedbackOutcome !== null) {
          reportFeedback(client, {
            signal_id: entry.signalId,
            trade_id: formatTradeId('manual', entry.signalId),
            outcome: feedbackOutcome,
            exit_reason: formatExitReason('manual', entry.horizon, chosen),
          }).catch((err) => {
            console.warn(
              `[watchlist] POST /feedback manual override failed for ${entry.signalId}:`,
              (err as Error).message,
            );
          });
        }
      };

      Alert.alert(
        'Résultat observé',
        `${entry.entityId} · ${entry.direction.toUpperCase()} · ${entry.horizon}\nChoisis le verdict après observation du marché.`,
        [
          { text: 'Confirmé ✓', onPress: () => applyOverride('confirmed') },
          { text: 'Infirmé ✗', onPress: () => applyOverride('refuted') },
          { text: 'Sans verdict', onPress: () => applyOverride('n_a') },
          { text: 'Annuler', style: 'cancel' },
        ],
        { cancelable: true },
      );
    },
    [client, setOutcome],
  );

  // F2 audit UX 2026-05-17 : 2 lignes lisibles.
  //   Ligne 1 : entity · direction badge · horizon   |   timestamp
  //   Ligne 2 : outcome badge · veracity %           (confidence retiré,
  //             déjà visible dans le détail du signal)
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
        <View style={styles.rowLine}>
          <ThemedText type="defaultSemiBold" style={styles.entityLabel}>
            {entry.entityId}
          </ThemedText>
          <View style={[styles.directionBadge, { backgroundColor: dirColor }]}>
            <ThemedText style={styles.directionLabel}>
              {entry.direction.toUpperCase()}
            </ThemedText>
          </View>
          <ThemedText style={styles.horizonLabel}>{entry.horizon}</ThemedText>
          <ThemedText style={styles.timestamp}>{timeAgo(entry.addedAt)}</ThemedText>
        </View>
        <View style={styles.rowLine}>
          <Pressable
            onPress={() => openOverrideModal(entry)}
            hitSlop={6}
            accessibilityRole="button"
            accessibilityLabel="Modifier le résultat observé"
            style={({ pressed }) => [
              styles.outcomeBadge,
              {
                borderColor: outcomeColor,
                opacity: pressed ? 0.55 : 1,
              },
            ]}>
            <ThemedText style={[styles.outcomeLabel, { color: outcomeColor }]}>
              {OUTCOME_LABELS[entry.outcome]}
              {entry.manuallyResolved ? ' ✎' : ''}
            </ThemedText>
          </Pressable>
          <ThemedText style={styles.veracityLabel}>
            verac {(entry.veracity * 100).toFixed(0)}%
          </ThemedText>
        </View>
        <Pressable
          onPress={() => confirmRemove(entry)}
          hitSlop={12}
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
          Signaux marqués pour follow-up. L&apos;outcome est résolu automatiquement à l&apos;expiration de l&apos;horizon (1h flash / 5j swing / 90j macro). Tape un badge pour ajuster le verdict manuellement.
        </ThemedText>
        {personalStats.total > 0 ? (
          <PersonalHitRateCard
            stats={personalStats}
            globalReference={globalRef}
            comparisonLabel={comparison?.label ?? null}
            loading={globalLoading}
            error={globalError}
          />
        ) : null}
        {personalStats.total > 0 ? (
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
    paddingRight: 40,
    gap: 8,
    position: 'relative',
  },
  rowLine: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  entityLabel: {
    fontSize: 15,
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
  horizonLabel: {
    fontSize: 12,
    opacity: 0.7,
    textTransform: 'uppercase',
  },
  timestamp: {
    fontSize: 11,
    opacity: 0.6,
    marginLeft: 'auto',
  },
  outcomeBadge: {
    borderWidth: 1,
    borderRadius: 4,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  outcomeLabel: {
    fontSize: 11,
    fontWeight: '600',
  },
  veracityLabel: {
    fontSize: 12,
    opacity: 0.75,
  },
  removeBtn: {
    position: 'absolute',
    top: 8,
    right: 10,
    width: 28,
    height: 28,
    alignItems: 'center',
    justifyContent: 'center',
  },
  removeBtnLabel: {
    fontSize: 22,
    lineHeight: 24,
    fontWeight: '700',
  },
});
