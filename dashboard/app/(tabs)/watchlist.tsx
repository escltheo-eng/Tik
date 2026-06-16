import { useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { PersonalHitRateCard } from '@/components/watchlist/personal-hit-rate-card';
import { Cosmic, TitleShadow, directionMeta, serifTitleFamily } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
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
  inconclusive: 'Non concluant',
  n_a: 'N/A',
};

// Couleurs d'outcome adaptées au fond sombre cosmique (texte/bordure).
const OUTCOME_COLORS: Record<WatchlistEntry['outcome'], string> = {
  pending: '#8693a8',
  confirmed: Cosmic.long,
  refuted: Cosmic.short,
  inconclusive: Cosmic.neutral,
  n_a: Cosmic.textFaint,
};

export default function WatchlistScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
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

  // 2 lignes lisibles : (1) entity · direction · horizon · âge ; (2) outcome · veracity.
  const renderEntry = (entry: WatchlistEntry) => {
    const dir = directionMeta(entry.direction);
    const outcomeColor = OUTCOME_COLORS[entry.outcome];
    return (
      <Pressable
        key={entry.signalId}
        onPress={() => router.push(`/signal-cosmique/${encodeURIComponent(entry.signalId)}`)}
        style={({ pressed }) => [styles.row, { opacity: pressed ? 0.7 : 1 }]}>
        <View style={styles.rowLine}>
          <Text style={styles.entityLabel}>{entry.entityId}</Text>
          <View style={[styles.tag, { backgroundColor: dir.color + '22', borderColor: dir.color + '66' }]}>
            <Text style={[styles.tagText, { color: dir.color }]}>{dir.label}</Text>
          </View>
          <Text style={styles.horizonLabel}>{entry.horizon}</Text>
          <Text style={styles.timestamp}>{timeAgo(entry.addedAt)}</Text>
        </View>
        <View style={styles.rowLine}>
          <Pressable
            onPress={() => openOverrideModal(entry)}
            hitSlop={6}
            accessibilityRole="button"
            accessibilityLabel="Modifier le résultat observé"
            style={({ pressed }) => [
              styles.outcomeBadge,
              { borderColor: outcomeColor, opacity: pressed ? 0.55 : 1 },
            ]}>
            <Text style={[styles.outcomeLabel, { color: outcomeColor }]}>
              {OUTCOME_LABELS[entry.outcome]}
              {entry.manuallyResolved ? ' ✎' : ''}
            </Text>
          </Pressable>
          <Text style={styles.veracityLabel}>verac {(entry.veracity * 100).toFixed(0)}%</Text>
        </View>
        <Pressable
          onPress={() => confirmRemove(entry)}
          hitSlop={12}
          style={({ pressed }) => [styles.removeBtn, { opacity: pressed ? 0.4 : 0.7 }]}
          accessibilityRole="button"
          accessibilityLabel="Retirer de la watchlist">
          <Text style={styles.removeBtnLabel}>×</Text>
        </Pressable>
      </Pressable>
    );
  };

  return (
    <CosmicBackground>
      <View style={[styles.container, { paddingTop: insets.top + 8 }]}>
        <View style={styles.header}>
          <Text style={styles.title}>Watchlist</Text>
          <Text style={styles.subtitle}>
            {"Signaux marqués pour follow-up. L'outcome est résolu automatiquement à l'expiration " +
              "de l'horizon (1h flash / 5j swing / 90j macro). Tape un badge pour ajuster le " +
              'verdict manuellement.'}
          </Text>
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
                style={({ pressed }) => [styles.actionBtn, { opacity: pressed ? 0.6 : 1 }]}>
                <Text style={styles.actionLabel}>Tout effacer</Text>
              </Pressable>
            </View>
          ) : null}
        </View>

        {!hydrated ? null : entries.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>Aucun signal suivi</Text>
            <Text style={styles.emptyText}>
              {"Ouvre un signal depuis l'onglet Signals et tape sur ★ Suivre pour le marquer. Tu " +
                "pourras ensuite suivre l'évolution dans cet onglet et mesurer ton hit rate personnel."}
            </Text>
          </View>
        ) : (
          <ScrollView contentContainerStyle={styles.listContent}>
            {sortedEntries.map(renderEntry)}
          </ScrollView>
        )}
      </View>
    </CosmicBackground>
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
  title: {
    ...TitleShadow.glow,
    fontFamily: serifTitleFamily,
    color: Cosmic.text,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  subtitle: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 18,
  },
  actions: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 4,
  },
  actionBtn: {
    borderWidth: 1,
    borderColor: Cosmic.borderStrong,
    borderRadius: 16,
    paddingVertical: 6,
    paddingHorizontal: 12,
  },
  actionLabel: {
    color: Cosmic.textDim,
    fontSize: 13,
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
    gap: 12,
  },
  emptyTitle: {
    color: Cosmic.text,
    fontSize: 18,
    fontWeight: '700',
  },
  emptyText: {
    color: Cosmic.textDim,
    textAlign: 'center',
    fontSize: 14,
    lineHeight: 20,
  },
  listContent: {
    paddingBottom: 24,
    gap: 8,
  },
  row: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 12,
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
    color: Cosmic.text,
    fontSize: 15,
    fontWeight: '700',
  },
  tag: {
    borderWidth: 1,
    borderRadius: 7,
    paddingVertical: 3,
    paddingHorizontal: 8,
    minWidth: 58,
    alignItems: 'center',
  },
  tagText: {
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  horizonLabel: {
    color: Cosmic.textFaint,
    fontSize: 12,
    fontFamily: Fonts.mono,
    textTransform: 'uppercase',
  },
  timestamp: {
    color: Cosmic.textFaint,
    fontSize: 11,
    marginLeft: 'auto',
  },
  outcomeBadge: {
    borderWidth: 1,
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  outcomeLabel: {
    fontSize: 11,
    fontWeight: '700',
  },
  veracityLabel: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontFamily: Fonts.mono,
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
    color: Cosmic.textDim,
    fontSize: 22,
    lineHeight: 24,
    fontWeight: '700',
  },
});
