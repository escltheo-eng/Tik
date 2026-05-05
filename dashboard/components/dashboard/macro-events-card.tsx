/**
 * MacroEventsCard — calendrier macro/géopolitique programmé.
 *
 * Lacune B Phase B1 J+10 (cf. ADR-017). Pattern OSINT pro : dates
 * officielles citant leurs sources (FRED Releases API + Fed Reserve
 * statique pour FOMC), l'humain anticipe ses positions. Zéro signal
 * trading généré, zéro hallucination LLM.
 *
 * Mode compact (Home) : 1 ligne mise en avant pour le next event HIGH
 * + 3 events suivants en liste compacte. Tap → `/macro` pour la liste full.
 */

import { Link } from 'expo-router';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
} from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { MacroEvent } from '@/src/api/types';
import { formatLocal, timeUntil } from '@/src/utils/time';

export interface MacroEventsCardProps {
  events: MacroEvent[];
  loading?: boolean;
  error?: string | null;
  /** Cap d'affichage en mode compact (défaut 4 = 1 mis en avant + 3 suivants). */
  displayLimit?: number;
  /** Si true, affiche le bouton "Voir tous". */
  showSeeAll?: boolean;
}

function importanceColor(importance: string): string {
  switch (importance) {
    case 'HIGH':
      return '#c0392b';
    case 'MEDIUM':
      return '#e67e22';
    case 'LOW':
      return '#7f8c8d';
    default:
      return '#7f8c8d';
  }
}

function importanceLabel(importance: string): string {
  return importance.toUpperCase();
}

function eventLabel(event: MacroEvent): string {
  // Libellé court mnémotechnique pour la liste compacte.
  // Le nom complet reste dans la route détail /macro.
  switch (event.event_code) {
    case 'FOMC_MEETING':
      return 'FOMC';
    case 'NFP':
      return 'NFP (emploi US)';
    case 'CPI':
      return 'CPI (inflation US)';
    case 'PPI':
      return 'PPI (prix prod.)';
    case 'GDP':
      return 'GDP (croissance)';
    case 'RETAIL_SALES':
      return 'Retail Sales';
    case 'INDUSTRIAL_PRODUCTION':
      return 'Industrial Prod.';
    case 'INITIAL_CLAIMS':
      return 'Initial Claims';
    default:
      return event.event_name;
  }
}

export function MacroEventsCard({
  events,
  loading,
  error,
  displayLimit = 4,
  showSeeAll = true,
}: MacroEventsCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];

  // Sépare le next event mis en avant (premier de la liste) des suivants.
  const visible = events.slice(0, displayLimit);
  const featured = visible[0];
  const followUps = visible.slice(1);

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Calendrier macro</ThemedText>
        <ThemedText style={styles.periodLabel}>7 j à venir</ThemedText>
      </ThemedView>

      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : loading && events.length === 0 ? (
        <ThemedView style={[styles.loading, { backgroundColor: 'transparent' }]}>
          <ActivityIndicator size="small" />
        </ThemedView>
      ) : !featured ? (
        <ThemedText style={styles.emptyLabel}>
          Aucun event macro programmé sur cette fenêtre.
        </ThemedText>
      ) : (
        <>
          {/* Featured: next event HIGH/MEDIUM/LOW avec countdown */}
          <ThemedView
            style={[
              styles.featured,
              { borderColor: importanceColor(featured.importance) },
            ]}>
            <ThemedView
              style={[styles.featuredTopRow, { backgroundColor: 'transparent' }]}>
              <ThemedView
                style={[
                  styles.importanceBadge,
                  { backgroundColor: importanceColor(featured.importance) },
                ]}>
                <ThemedText style={styles.importanceLabel}>
                  {importanceLabel(featured.importance)}
                </ThemedText>
              </ThemedView>
              <ThemedText style={styles.featuredCountdown}>
                {timeUntil(featured.scheduled_for)}
              </ThemedText>
            </ThemedView>
            <ThemedText style={styles.featuredEventLabel}>
              {eventLabel(featured)}
            </ThemedText>
            <ThemedText style={styles.metaLabel}>
              {formatLocal(featured.scheduled_for)} · {featured.assets_impacted.join(', ')}
            </ThemedText>
          </ThemedView>

          {/* Liste compacte des events suivants */}
          {followUps.length > 0 ? (
            <ThemedView style={[styles.followUps, { backgroundColor: 'transparent' }]}>
              {followUps.map((ev) => (
                <ThemedView
                  key={ev.id}
                  style={[
                    styles.followUpRow,
                    { borderBottomColor: palette.icon },
                  ]}>
                  <ThemedView
                    style={[
                      styles.importanceDot,
                      { backgroundColor: importanceColor(ev.importance) },
                    ]}
                  />
                  <ThemedText style={styles.followUpLabel} numberOfLines={1}>
                    {eventLabel(ev)}
                  </ThemedText>
                  <ThemedText style={styles.metaLabel}>
                    {timeUntil(ev.scheduled_for)}
                  </ThemedText>
                </ThemedView>
              ))}
            </ThemedView>
          ) : null}
        </>
      )}

      {showSeeAll && events.length > 0 ? (
        <Link href="/macro" asChild>
          <Pressable
            style={({ pressed }) => [
              styles.seeAll,
              { borderColor: palette.icon, opacity: pressed ? 0.7 : 1 },
            ]}>
            <ThemedText style={styles.seeAllLabel}>
              Voir tout le calendrier
            </ThemedText>
          </Pressable>
        </Link>
      ) : null}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 4,
  },
  periodLabel: {
    fontSize: 12,
    opacity: 0.6,
  },
  loading: {
    alignItems: 'center',
    paddingVertical: 16,
  },
  emptyLabel: {
    opacity: 0.6,
    paddingVertical: 8,
  },
  errorText: {
    color: '#c0392b',
    fontSize: 13,
  },
  featured: {
    borderLeftWidth: 4,
    paddingLeft: 12,
    paddingVertical: 6,
    gap: 4,
  },
  featuredTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  featuredEventLabel: {
    fontSize: 16,
    fontWeight: '700',
  },
  featuredCountdown: {
    fontSize: 13,
    fontWeight: '600',
    opacity: 0.85,
  },
  importanceBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 3,
  },
  importanceLabel: {
    color: '#ffffff',
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  metaLabel: {
    fontSize: 11,
    opacity: 0.65,
  },
  followUps: {
    gap: 0,
  },
  followUpRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  importanceDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  followUpLabel: {
    flex: 1,
    fontSize: 14,
  },
  seeAll: {
    marginTop: 4,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: 'center',
  },
  seeAllLabel: {
    fontSize: 13,
    fontWeight: '600',
  },
});
