/**
 * TopHeadlinesCard — carte Home affichant les derniers titres OSINT bruts.
 *
 * Phase 1 trading manuel J+10. Pattern OSINT pro : titres bruts citant
 * leurs sources, l'humain interprète. Zéro synthèse LLM, zéro hallucination.
 *
 * - Sélecteur BTC/GOLD (segmented simple)
 * - Cap 5 sur Home (option `compact`)
 * - Tap sur un titre → ouvre l'article dans le navigateur natif
 * - Bouton "Voir tous (jusqu'à 25)" → route `/headlines/[entityId]`
 */

import { Link } from 'expo-router';
import {
  ActivityIndicator,
  Linking,
  Pressable,
  StyleSheet,
} from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { Headline } from '@/src/api/types';
import { timeAgo } from '@/src/utils/time';

export interface TopHeadlinesCardProps {
  /** Liste de titres déjà fetchés. */
  headlines: Headline[];
  /** Entity sélectionnée (BTC/GOLD/...). */
  entityId: string;
  /** Callback quand l'utilisateur change d'entity via le sélecteur. */
  onEntityChange?: (entityId: string) => void;
  /** Choix possibles pour le sélecteur (défaut: BTC, GOLD). */
  entityOptions?: readonly string[];
  /** Cap d'affichage (défaut 5 — pour le mode compact Home). */
  displayLimit?: number;
  /** Si true, affiche le bouton "Voir tous". */
  showSeeAll?: boolean;
  loading?: boolean;
  error?: string | null;
}

const DEFAULT_ENTITY_OPTIONS = ['BTC', 'GOLD'] as const;

function sentimentColor(sentiment: string): string {
  switch (sentiment) {
    case 'bull':
      return '#27ae60';
    case 'bear':
      return '#c0392b';
    default:
      return '#7f8c8d';
  }
}

function sentimentLabel(sentiment: string): string {
  switch (sentiment) {
    case 'bull':
      return 'BULL';
    case 'bear':
      return 'BEAR';
    default:
      return 'NEUTRAL';
  }
}

function sourceShortLabel(source: string): string {
  // Raccourcis lisibles côté UI — la source brute reste exposée si besoin.
  switch (source) {
    case 'google_news_rss':
      return 'Google News';
    case 'cryptocompare_news':
      return 'CryptoCompare';
    case 'reddit_btc':
      return 'Reddit';
    default:
      return source;
  }
}

export function TopHeadlinesCard({
  headlines,
  entityId,
  onEntityChange,
  entityOptions = DEFAULT_ENTITY_OPTIONS,
  displayLimit = 5,
  showSeeAll = true,
  loading,
  error,
}: TopHeadlinesCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];
  const visible = headlines.slice(0, displayLimit);

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Top headlines</ThemedText>
        <ThemedText style={styles.periodLabel}>24 h · multi-source</ThemedText>
      </ThemedView>

      {onEntityChange ? (
        <ThemedView style={[styles.selector, { backgroundColor: 'transparent' }]}>
          {entityOptions.map((opt) => {
            const active = opt === entityId;
            return (
              <Pressable
                key={opt}
                onPress={() => onEntityChange(opt)}
                style={({ pressed }) => [
                  styles.selectorBtn,
                  {
                    backgroundColor: active ? palette.tint : 'transparent',
                    borderColor: palette.icon,
                    opacity: pressed ? 0.7 : 1,
                  },
                ]}>
                <ThemedText
                  style={[
                    styles.selectorLabel,
                    { color: active ? '#ffffff' : palette.text },
                  ]}>
                  {opt}
                </ThemedText>
              </Pressable>
            );
          })}
        </ThemedView>
      ) : null}

      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : loading && headlines.length === 0 ? (
        <ThemedView style={[styles.loading, { backgroundColor: 'transparent' }]}>
          <ActivityIndicator size="small" />
        </ThemedView>
      ) : visible.length === 0 ? (
        <ThemedText style={styles.emptyLabel}>
          Aucun titre publié sur cette fenêtre.
        </ThemedText>
      ) : (
        <ThemedView style={[styles.list, { backgroundColor: 'transparent' }]}>
          {visible.map((h, idx) => (
            <Pressable
              key={`${h.source}-${idx}-${h.title.slice(0, 32)}`}
              onPress={() => {
                // N'ouvre que http(s) absolu : un titre OSINT externe pourrait
                // porter une URL javascript:/tel:/deep-link déclenchant une
                // action native sans confirmation (audit 2026-05-24 H3).
                const u = h.url?.trim();
                if (u && /^https?:\/\//i.test(u)) void Linking.openURL(u).catch(() => {});
              }}
              style={({ pressed }) => [
                styles.headlineRow,
                {
                  borderBottomColor: palette.icon,
                  opacity: pressed && h.url ? 0.6 : 1,
                },
              ]}>
              <ThemedView style={[styles.headlineTopRow, { backgroundColor: 'transparent' }]}>
                <ThemedView
                  style={[
                    styles.sentimentBadge,
                    { backgroundColor: sentimentColor(h.sentiment) },
                  ]}>
                  <ThemedText style={styles.sentimentLabel}>
                    {sentimentLabel(h.sentiment)}
                  </ThemedText>
                </ThemedView>
                <ThemedText style={styles.metaLabel}>
                  {sourceShortLabel(h.source)} · {h.publisher}
                </ThemedText>
                <ThemedText style={styles.metaLabel}>
                  {timeAgo(h.published_at ?? h.fetched_at)}
                </ThemedText>
              </ThemedView>
              <ThemedText style={styles.headlineTitle} numberOfLines={3}>
                {h.title}
              </ThemedText>
            </Pressable>
          ))}
        </ThemedView>
      )}

      {showSeeAll && visible.length > 0 ? (
        <Link href={`/headlines/${encodeURIComponent(entityId)}`} asChild>
          <Pressable
            style={({ pressed }) => [
              styles.seeAll,
              { borderColor: palette.icon, opacity: pressed ? 0.7 : 1 },
            ]}>
            <ThemedText style={styles.seeAllLabel}>
              Voir tous (jusqu&apos;à 25)
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
  selector: {
    flexDirection: 'row',
    gap: 8,
  },
  selectorBtn: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 16,
    borderWidth: 1,
  },
  selectorLabel: {
    fontSize: 13,
    fontWeight: '600',
    letterSpacing: 0.3,
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
  list: {
    gap: 0,
  },
  headlineRow: {
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 4,
  },
  headlineTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap',
  },
  sentimentBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 3,
  },
  sentimentLabel: {
    color: '#ffffff',
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  metaLabel: {
    fontSize: 11,
    opacity: 0.65,
  },
  headlineTitle: {
    fontSize: 14,
    lineHeight: 18,
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
