/**
 * Route détail « Dernières actus » — cosmique, cap 25 titres avec dates.
 *
 * Accédée via le bouton « Voir toutes les actus » de `CosmicHeadlines` (cockpit) :
 * on « entre » dans la carte. Réutilise `CosmicHeadlines` (tag BULL/BEAR, sélecteur
 * BTC/GOLD, date de publication par ligne). Pull-to-refresh. Header cosmique
 * (enregistré dans `app/_layout.tsx`). Données 100 % réelles.
 */

import { useLocalSearchParams } from 'expo-router';
import { useCallback, useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet } from 'react-native';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { CosmicHeadlines } from '@/components/cosmic/cosmic-news';
import { Cosmic } from '@/constants/cosmic';
import { useTick } from '@/src/hooks/use-tick';
import { useTopHeadlines } from '@/src/hooks/useTopHeadlines';

export default function HeadlinesScreen() {
  const params = useLocalSearchParams<{ entityId: string }>();
  const initialEntity = params.entityId || 'BTC';
  const [entityId, setEntityId] = useState<string>(initialEntity);

  // Cap dur à 25 — au-delà c'est illisible mobile et la demi-vie sentiment est courte.
  const { headlines, loading, error, refresh } = useTopHeadlines(entityId, {
    limit: 25,
    sinceHours: 24,
  });

  // Tick partagé : réécrit les « il y a X min » toutes les 30 s.
  useTick();

  const [refreshing, setRefreshing] = useState(false);
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await refresh();
    } finally {
      setRefreshing(false);
    }
  }, [refresh]);

  return (
    <CosmicBackground>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Cosmic.accent} />
        }>
        <CosmicHeadlines
          headlines={headlines}
          entityId={entityId}
          onEntityChange={setEntityId}
          displayLimit={25}
          loading={loading}
          error={error}
        />
      </ScrollView>
    </CosmicBackground>
  );
}

const styles = StyleSheet.create({
  content: {
    padding: 16,
    gap: 12,
  },
});
