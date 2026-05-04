/**
 * Route détail Top headlines — vue plein écran cap 25 titres.
 *
 * Accédée via le bouton "Voir tous" de la carte `TopHeadlinesCard`.
 * L'entityId est extrait des params de route (expo-router).
 */

import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
} from 'react-native';

import { TopHeadlinesCard } from '@/components/dashboard/top-headlines-card';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useTick } from '@/src/hooks/use-tick';
import { useTopHeadlines } from '@/src/hooks/useTopHeadlines';

export default function HeadlinesScreen() {
  const params = useLocalSearchParams<{ entityId: string }>();
  const initialEntity = params.entityId || 'BTC';
  const [entityId, setEntityId] = useState<string>(initialEntity);
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];

  // Cap dur à 25 sur cette vue — au-delà ça devient illisible mobile et
  // les news ont une demi-vie sentiment trop courte pour valoir plus.
  const { headlines, loading, error, refresh } = useTopHeadlines(entityId, {
    limit: 25,
    sinceHours: 24,
  });

  // Tick partagé pour réécrire les "il y a X min" toutes les 30s.
  useTick();

  return (
    <ScrollView style={styles.scroll}>
      <ThemedView style={styles.container}>
        <ThemedView style={styles.titleRow}>
          <ThemedText type="title">Top headlines</ThemedText>
          <Pressable
            onPress={() => void refresh()}
            style={({ pressed }) => [
              styles.refresh,
              {
                borderColor: palette.icon,
                opacity: pressed ? 0.6 : 1,
              },
            ]}>
            <ThemedText style={styles.refreshLabel}>Rafraîchir</ThemedText>
          </Pressable>
        </ThemedView>

        <ThemedText style={styles.subtitle}>
          Multi-source brute (Google News, CryptoCompare, Reddit) — fenêtre 24 h,
          tri crédibilité × récence.
        </ThemedText>

        <TopHeadlinesCard
          headlines={headlines}
          entityId={entityId}
          onEntityChange={setEntityId}
          displayLimit={25}
          showSeeAll={false}
          loading={loading}
          error={error}
        />
      </ThemedView>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: {
    flex: 1,
  },
  container: {
    padding: 16,
    gap: 12,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  subtitle: {
    fontSize: 13,
    opacity: 0.7,
  },
  refresh: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
    borderWidth: 1,
  },
  refreshLabel: {
    fontSize: 13,
    fontWeight: '600',
  },
});
