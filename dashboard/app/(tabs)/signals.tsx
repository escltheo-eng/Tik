import { useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  StyleSheet,
  View,
  type ListRenderItem,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AntiFakeNewsBadge } from '@/components/dashboard/anti-fake-news-badge';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { Signal } from '@/src/api/types';
import { computeFlashStability } from '@/src/flash/stability';
import { useSignalStream } from '@/src/hooks/useSignalStream';
import { useTick } from '@/src/hooks/use-tick';
import { timeAgo } from '@/src/utils/time';

const ENTITY_FILTERS: { label: string; value: string | undefined }[] = [
  { label: 'Tous', value: undefined },
  { label: 'BTC', value: 'BTC' },
  { label: 'GOLD', value: 'GOLD' },
];

const HORIZON_FILTERS: { label: string; value: string | undefined }[] = [
  { label: 'Tous', value: undefined },
  { label: 'Flash', value: 'flash' },
  { label: 'Swing', value: 'swing' },
  { label: 'Macro', value: 'macro' },
];

// Fenêtres temporelles pour le preload signaux historiques.
// 24h utilise /signals/latest (cap 200, mais on demande 100). 5j/30j
// utilisent /signals (search) qui supporte jusqu'à 720h et limit 1000.
// Le WebSocket continue de prepend les nouveaux signaux par-dessus.
// Avec ~100 signaux/jour, 30j ≈ 3000 signaux → cap backend 1000 → on
// affiche les 1000 plus récents sur la fenêtre demandée (≈ 10j réels).
const DURATION_FILTERS: { label: string; sinceHours: number | undefined; preloadLimit: number }[] = [
  { label: '24h', sinceHours: undefined, preloadLimit: 100 },
  { label: '5j',  sinceHours: 120,       preloadLimit: 500 },
  { label: '30j', sinceHours: 720,       preloadLimit: 1000 },
];

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

function connectionLabel(state: string): string {
  switch (state) {
    case 'connected':
      return 'Live';
    case 'connecting':
      return 'Connexion…';
    case 'reconnecting':
      return 'Reconnexion…';
    case 'auth_error':
      return 'Auth refusée';
    case 'stopped':
      return 'Arrêté';
    default:
      return 'Inactif';
  }
}

function connectionColor(state: string): string {
  switch (state) {
    case 'connected':
      return '#27ae60';
    case 'connecting':
    case 'reconnecting':
      return '#f39c12';
    case 'auth_error':
      return '#c0392b';
    default:
      return '#7f8c8d';
  }
}

export default function SignalsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];

  const [entity, setEntity] = useState<string | undefined>(undefined);
  const [horizon, setHorizon] = useState<string | undefined>(undefined);
  const [durationIdx, setDurationIdx] = useState<number>(0);

  const duration = DURATION_FILTERS[durationIdx];

  const { signals, connectionState, error, preloadLoading, preloadError } = useSignalStream({
    entity,
    horizon,
    sinceHours: duration.sinceHours,
    preloadLimit: duration.preloadLimit,
    maxSignals: duration.preloadLimit,
  });
  // Force re-render des items FlatList toutes les 30 s pour rafraîchir les
  // libellés "il y a X" (la FlatList mémoïse ses rows par défaut).
  const tick = useTick();

  // Stabilité flash BTC (Paquet 42, logique pure réutilisée) : le flash flippe
  // long↔short sans edge (~7 min). On garde la direction visible mais on ajoute
  // un repère "court terme indécis" sur les lignes flash BTC quand c'est haché.
  // Calculé sur les signaux bruts (indépendant des filtres actifs) ; `tick` le
  // rafraîchit avec la fenêtre glissante. Re-render FlatList via extraData.
  const flashChoppy = useMemo(
    () => computeFlashStability(signals, { entityId: 'BTC' }).state === 'choppy',
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signals, tick],
  );

  const renderItem: ListRenderItem<Signal> = useMemo(() => {
    const SignalRow: ListRenderItem<Signal> = ({ item }) => (
      <Pressable
        onPress={() => router.push(`/signal/${encodeURIComponent(item.id)}`)}
        style={({ pressed }) => [
          styles.row,
          {
            borderColor: palette.icon,
            backgroundColor: pressed ? (colorScheme === 'dark' ? '#1a1d20' : '#f5f5f5') : 'transparent',
          },
        ]}>
        <ThemedView style={[styles.rowHeader, { backgroundColor: 'transparent' }]}>
          <ThemedText type="defaultSemiBold">{item.entity_id}</ThemedText>
          <ThemedText style={styles.timestamp}>{timeAgo(item.timestamp)}</ThemedText>
        </ThemedView>

        <ThemedView style={[styles.rowMiddle, { backgroundColor: 'transparent' }]}>
          <View style={[styles.directionBadge, { backgroundColor: directionColor(item.direction) }]}>
            <ThemedText style={styles.directionLabel}>{item.direction.toUpperCase()}</ThemedText>
          </View>
          <ThemedText style={styles.horizonLabel}>{item.horizon}</ThemedText>
          <AntiFakeNewsBadge status={item.circuit_breaker_status} compact />
          {item.horizon === 'flash' && item.entity_id === 'BTC' && flashChoppy ? (
            <Pressable
              onPress={() =>
                Alert.alert(
                  'Court terme indécis',
                  'Le flash a changé plusieurs fois de direction (long↔short) sur ' +
                    'les dernières ~45 min. Le très court terme est haché : la direction ' +
                    'affichée sert au timing, pas à suivre telle quelle.\n\n' +
                    'À ne pas confondre avec le badge anti-fake-news (AFN, orange) : ' +
                    'l’AFN signale un désaccord entre sources SUR UN signal ; ce repère ' +
                    'signale que la direction CHANGE souvent DANS LE TEMPS.',
                  [{ text: 'OK', style: 'default' }],
                )
              }
              hitSlop={6}
              accessibilityRole="button"
              accessibilityLabel="Court terme indécis — appuyer pour en savoir plus">
              <ThemedText style={styles.choppyTag}>🔀 court terme indécis</ThemedText>
            </Pressable>
          ) : null}
        </ThemedView>

        <ThemedView style={[styles.rowFooter, { backgroundColor: 'transparent' }]}>
          <ThemedText style={styles.metric}>
            conv {(item.confidence * 100).toFixed(0)}%
          </ThemedText>
          <ThemedText style={styles.metric}>
            verac {(item.veracity * 100).toFixed(0)}%
          </ThemedText>
          <ThemedText style={styles.metric}>
            sources {item.sources_count}
          </ThemedText>
        </ThemedView>
      </Pressable>
    );
    return SignalRow;
  }, [router, palette.icon, colorScheme, flashChoppy]);

  const filterPill = (label: string, active: boolean, onPress: () => void) => (
    <Pressable
      key={label}
      onPress={onPress}
      style={({ pressed }) => [
        styles.pill,
        {
          backgroundColor: active ? palette.tint : 'transparent',
          borderColor: active ? palette.tint : palette.icon,
          opacity: pressed ? 0.7 : 1,
        },
      ]}>
      <ThemedText style={[styles.pillLabel, { color: active ? '#ffffff' : palette.text }]}>
        {label}
      </ThemedText>
    </Pressable>
  );

  return (
    <ThemedView style={[styles.container, { paddingTop: insets.top + 8 }]}>
      <ThemedView style={styles.header}>
        <ThemedView style={styles.headerTop}>
          <ThemedText type="title">Signals</ThemedText>
          <ThemedView style={styles.statusInline}>
            <View style={[styles.dot, { backgroundColor: connectionColor(connectionState) }]} />
            <ThemedText style={[styles.statusText, { color: connectionColor(connectionState) }]}>
              {connectionLabel(connectionState)}
            </ThemedText>
          </ThemedView>
        </ThemedView>

        <ThemedView style={styles.filterRow}>
          {DURATION_FILTERS.map((d, idx) =>
            filterPill(d.label, durationIdx === idx, () => setDurationIdx(idx)),
          )}
        </ThemedView>

        <ThemedView style={styles.filterRow}>
          {ENTITY_FILTERS.map((f) =>
            filterPill(f.label, entity === f.value, () => setEntity(f.value)),
          )}
        </ThemedView>

        <ThemedView style={styles.filterRow}>
          {HORIZON_FILTERS.map((f) =>
            filterPill(f.label, horizon === f.value, () => setHorizon(f.value)),
          )}
        </ThemedView>

        {error || preloadError ? (
          <ThemedView style={styles.errorBox}>
            <ThemedText style={{ color: '#c0392b' }}>
              {error ?? preloadError}
            </ThemedText>
          </ThemedView>
        ) : null}
      </ThemedView>

      {preloadLoading && signals.length === 0 ? (
        <ThemedView style={styles.empty}>
          <ActivityIndicator size="large" />
          <ThemedText style={styles.emptyText}>Chargement des derniers signaux…</ThemedText>
        </ThemedView>
      ) : signals.length === 0 ? (
        <ThemedView style={styles.empty}>
          <ThemedText style={styles.emptyText}>
            Aucun signal pour l’instant. Le flux est ouvert, les nouveaux signaux apparaîtront ici dès qu’ils seront émis par le core.
          </ThemedText>
        </ThemedView>
      ) : (
        <FlatList
          data={signals}
          extraData={`${tick}-${flashChoppy}`}
          keyExtractor={(item) => item.id}
          renderItem={renderItem}
          contentContainerStyle={styles.listContent}
          ItemSeparatorComponent={() => <View style={styles.separator} />}
        />
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
    gap: 12,
  },
  headerTop: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  statusInline: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
  },
  dot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  filterRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  pill: {
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  pillLabel: {
    fontSize: 13,
    fontWeight: '600',
  },
  errorBox: {
    borderWidth: 1,
    borderColor: '#c0392b',
    borderRadius: 8,
    padding: 8,
    backgroundColor: 'rgba(192, 57, 43, 0.08)',
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 12,
  },
  emptyText: {
    textAlign: 'center',
    opacity: 0.7,
  },
  listContent: {
    paddingBottom: 24,
  },
  row: {
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
    gap: 8,
  },
  rowHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  timestamp: {
    fontSize: 12,
    opacity: 0.6,
  },
  rowMiddle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  directionBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  directionLabel: {
    color: '#ffffff',
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  horizonLabel: {
    fontSize: 12,
    opacity: 0.7,
    textTransform: 'uppercase',
  },
  choppyTag: {
    // Indigo — volontairement DISTINCT de l'orange AFN (#e67e22) pour ne pas
    // confondre "court terme haché" (temporel) avec "anti-fake-news" (1 signal).
    fontSize: 10,
    fontWeight: '700',
    color: '#5b54c9',
    backgroundColor: 'rgba(91, 84, 201, 0.14)',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    overflow: 'hidden',
  },
  alertBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  alertLabel: {
    color: '#ffffff',
    fontSize: 10,
    fontWeight: '700',
  },
  rowFooter: {
    flexDirection: 'row',
    gap: 12,
  },
  metric: {
    fontSize: 12,
    opacity: 0.7,
  },
  separator: {
    height: 8,
  },
});
