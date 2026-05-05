/**
 * Route détail Calendrier macro — vue plein écran avec filtres importance.
 *
 * Lacune B Phase B1 J+10 (cf. ADR-017). Accédée via le bouton "Voir tout
 * le calendrier" de la carte `MacroEventsCard` côté Home.
 *
 * Affiche jusqu'à 30 events programmés sur les 14 prochains jours, triés
 * ASC par scheduled_for (le prochain en premier). Filtre par niveau
 * d'importance via boutons toggle (HIGH / MEDIUM / LOW).
 */

import { useState } from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
} from 'react-native';

import { MacroEventsCard } from '@/components/dashboard/macro-events-card';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useTick } from '@/src/hooks/use-tick';
import { useUpcomingMacroEvents } from '@/src/hooks/useUpcomingMacroEvents';

type Importance = 'HIGH' | 'MEDIUM' | 'LOW';

const ALL_LEVELS: readonly Importance[] = ['HIGH', 'MEDIUM', 'LOW'] as const;

const LEVEL_LABEL: Record<Importance, string> = {
  HIGH: 'High',
  MEDIUM: 'Medium',
  LOW: 'Low',
};

export default function MacroEventsScreen() {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];

  const [activeLevels, setActiveLevels] = useState<Set<Importance>>(
    new Set(ALL_LEVELS),
  );
  const importanceFilter = Array.from(activeLevels);

  // 30 events max, 14 jours en avant — équilibre entre exhaustivité et
  // lisibilité mobile.
  const { events, loading, error, refresh } = useUpcomingMacroEvents({
    hours: 14 * 24,
    importance: importanceFilter.length === 0 ? undefined : importanceFilter,
    limit: 30,
  });

  useTick();

  const toggleLevel = (level: Importance) => {
    setActiveLevels((prev) => {
      const next = new Set(prev);
      if (next.has(level)) {
        next.delete(level);
      } else {
        next.add(level);
      }
      return next;
    });
  };

  return (
    <ScrollView style={styles.scroll}>
      <ThemedView style={styles.container}>
        <ThemedView style={styles.titleRow}>
          <ThemedText type="title">Calendrier macro</ThemedText>
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
          Events macro/géopolitique programmés — sources : FRED Releases API
          (US gov officiel) + Federal Reserve calendar (FOMC). 14 jours à
          venir, importance filtrée.
        </ThemedText>

        <ThemedView style={[styles.filters, { backgroundColor: 'transparent' }]}>
          {ALL_LEVELS.map((level) => {
            const active = activeLevels.has(level);
            return (
              <Pressable
                key={level}
                onPress={() => toggleLevel(level)}
                style={({ pressed }) => [
                  styles.filterBtn,
                  {
                    backgroundColor: active ? Colors.light.tint : 'transparent',
                    borderColor: palette.icon,
                    opacity: pressed ? 0.7 : 1,
                  },
                ]}>
                <ThemedText
                  style={[
                    styles.filterLabel,
                    { color: active ? '#ffffff' : palette.text },
                  ]}>
                  {LEVEL_LABEL[level]}
                </ThemedText>
              </Pressable>
            );
          })}
        </ThemedView>

        <MacroEventsCard
          events={events}
          loading={loading}
          error={error}
          displayLimit={30}
          showSeeAll={false}
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
  filters: {
    flexDirection: 'row',
    gap: 8,
  },
  filterBtn: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 16,
    borderWidth: 1,
  },
  filterLabel: {
    fontSize: 13,
    fontWeight: '600',
    letterSpacing: 0.3,
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
