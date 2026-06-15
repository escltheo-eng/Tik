/**
 * BreakingNewsCard — derniers titres géopol/macro à fort impact (ADR-027).
 *
 * Affiche les mêmes titres que ceux qui déclenchent l'alerte Telegram breaking
 * (BBC, Al Jazeera, Cointelegraph, Google News ciblé), plus récents en tête.
 * Chaque titre est tappable (ouvre l'article). Une légende rappelle, par
 * catégorie présente, COMMENT ça peut bouger le BTC — honnêtement dans les
 * deux sens (↓ / ↑).
 *
 * ⚠️ Alerting / contexte / discipline — PAS un signal d'achat/vente. Ne touche
 * jamais le combined_bias (NO-GO / ADR-018 inchangés). L'humain interprète.
 */

import { ActivityIndicator, Linking, Pressable, StyleSheet } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useBreakingNews } from '@/src/hooks/useBreakingNews';
import { timeAgo } from '@/src/utils/time';

const CATEGORY_META: Record<string, { emoji: string; mechanism: string }> = {
  'guerre/géopol': {
    emoji: '🌍',
    mechanism:
      'Escalade → « risk-off », BTC souvent ↓ ; désescalade/accord → appétit du risque, souvent ↑ (effet refuge réel mais inconstant).',
  },
  'politique US': {
    emoji: '🏛️',
    mechanism:
      'Choc fiscal/institutionnel → bouge le dollar & les taux US (dollar fort / taux ↑ = pression ↓).',
  },
  'tarifs/commerce': {
    emoji: '📦',
    mechanism:
      'Tarifs / guerre commerciale → inflation + « risk-off » → BTC souvent ↓ à court terme.',
  },
  'Fed/taux/macro': {
    emoji: '🏦',
    mechanism:
      'Moteur macro n°1 : Fed « hawkish » / taux ↑ → ↓ ; « dovish » / baisse de taux → ↑.',
  },
  'crypto/régulation': {
    emoji: '⚖️',
    mechanism: 'Effet direct : durcissement / interdiction → ↓ ; feu vert (ETF, cadre clair) → ↑.',
  },
  personnalités: {
    emoji: '🗣️',
    mechanism:
      'Figure pro-BTC (Saylor, BlackRock, Coinbase…) qui annonce un achat/soutien → lu haussier ↑ (souvent déjà anticipé) ; sortie/critique (Buffett, Schiff, Dimon, régulateur) → pression ↓. Schiff/Dalio = pro-or. À recouper avec le volume réel.',
  },
};

function categoryEmoji(category: string): string {
  return CATEGORY_META[category]?.emoji ?? '📰';
}

function reactionColor(pct: number): string {
  if (pct >= 0.5) return '#27ae60';
  if (pct <= -0.5) return '#c0392b';
  return '#7f8c8d';
}

const DISPLAY_LIMIT = 8;

export function BreakingNewsCard() {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];
  const { items, reactions, loading } = useBreakingNews(DISPLAY_LIMIT);

  const visible = items.slice(0, DISPLAY_LIMIT);
  const categoriesPresent = Array.from(new Set(visible.map((i) => i.category)));

  return (
    <ThemedView style={[styles.card, { borderColor: '#c0392b' }]}>
      <ThemedView style={styles.header}>
        <ThemedText type="defaultSemiBold">🚨 Breaking</ThemedText>
        <ThemedText style={styles.periodLabel}>géopol · macro · temps quasi réel</ThemedText>
      </ThemedView>
      <ThemedText style={styles.disclaimer}>
        Alerte / contexte — pas un signal d&apos;achat ou de vente. Vérifie ta position, ne
        trade pas dans la panique.
      </ThemedText>

      {loading && items.length === 0 ? (
        <ThemedView style={styles.loading}>
          <ActivityIndicator size="small" />
        </ThemedView>
      ) : visible.length === 0 ? (
        <ThemedText style={styles.empty}>
          Rien capté récemment. (Au démarrage, le système « avale » en silence les titres déjà
          publiés — la 1ʳᵉ alerte arrive sur la prochaine vraie news.)
        </ThemedText>
      ) : (
        <ThemedView style={styles.list}>
          {visible.map((it, idx) => (
            <Pressable
              key={`${it.source}-${idx}-${it.title.slice(0, 32)}`}
              onPress={() => {
                // N'ouvre que http(s) absolu (cohérent garde-fou H3 top-headlines).
                const u = it.url?.trim();
                if (u && /^https?:\/\//i.test(u)) void Linking.openURL(u).catch(() => {});
              }}
              style={({ pressed }) => [
                styles.row,
                { borderBottomColor: palette.icon, opacity: pressed && it.url ? 0.6 : 1 },
              ]}>
              <ThemedView style={styles.topRow}>
                <ThemedText style={styles.catBadge}>
                  {categoryEmoji(it.category)} {it.category}
                </ThemedText>
                <ThemedText style={styles.meta}>
                  {it.source} · {timeAgo(it.detected_at ?? it.published_at ?? '')}
                </ThemedText>
              </ThemedView>
              <ThemedText style={styles.title} numberOfLines={3}>
                {it.title_fr ?? it.title}
              </ThemedText>
            </Pressable>
          ))}
        </ThemedView>
      )}

      {reactions.length > 0 ? (
        <ThemedView style={styles.reactions}>
          <ThemedText style={styles.reactTitle}>
            📊 Réactions mesurées BTC + Or (factuel, pas une prédiction)
          </ThemedText>
          {reactions.map((rx, idx) => (
            <ThemedView key={`${rx.alerted_at}-${rx.horizon_h}-${idx}`} style={styles.reactRow}>
              <ThemedView style={styles.reactPctCol}>
                <ThemedText style={styles.reactLine}>
                  ₿{' '}
                  <ThemedText style={[styles.reactPctVal, { color: reactionColor(rx.pct) }]}>
                    {rx.pct >= 0 ? '+' : ''}
                    {rx.pct.toFixed(1)}%
                  </ThemedText>{' '}
                  <ThemedText style={styles.reactHorizon}>{rx.horizon_h}h</ThemedText>
                </ThemedText>
                {rx.gold_closed ? (
                  <ThemedText style={styles.reactGoldClosed}>🥇 marché fermé</ThemedText>
                ) : rx.gold_pct != null ? (
                  <ThemedText style={styles.reactLine}>
                    🥇{' '}
                    <ThemedText
                      style={[styles.reactPctVal, { color: reactionColor(rx.gold_pct) }]}>
                      {rx.gold_pct >= 0 ? '+' : ''}
                      {rx.gold_pct.toFixed(1)}%
                    </ThemedText>
                  </ThemedText>
                ) : null}
              </ThemedView>
              <ThemedText style={styles.reactCtx} numberOfLines={2}>
                {categoryEmoji(rx.category)} {rx.title}
              </ThemedText>
            </ThemedView>
          ))}
        </ThemedView>
      ) : null}

      {categoriesPresent.length > 0 ? (
        <ThemedView style={styles.legend}>
          <ThemedText style={styles.legendTitle}>Comment ça peut bouger le BTC</ThemedText>
          {categoriesPresent.map((cat) => (
            <ThemedText key={cat} style={styles.legendRow}>
              {categoryEmoji(cat)} <ThemedText style={styles.legendCat}>{cat}</ThemedText> —{' '}
              {CATEGORY_META[cat]?.mechanism ?? ''}
            </ThemedText>
          ))}
        </ThemedView>
      ) : null}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 4,
  },
  periodLabel: { fontSize: 12, opacity: 0.6 },
  disclaimer: { fontSize: 11, opacity: 0.7, fontStyle: 'italic' },
  loading: { alignItems: 'center', paddingVertical: 16 },
  empty: { opacity: 0.6, paddingVertical: 8, fontSize: 13 },
  list: { gap: 0 },
  row: {
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 4,
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    flexWrap: 'wrap',
  },
  catBadge: { fontSize: 11, fontWeight: '700', opacity: 0.85 },
  meta: { fontSize: 11, opacity: 0.65 },
  title: { fontSize: 14, lineHeight: 18 },
  legend: { marginTop: 4, gap: 3 },
  legendTitle: { fontSize: 12, fontWeight: '700', opacity: 0.8 },
  legendRow: { fontSize: 11, opacity: 0.75, lineHeight: 15 },
  legendCat: { fontWeight: '700' },
  reactions: { marginTop: 4, gap: 3, paddingTop: 6, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: '#888' },
  reactTitle: { fontSize: 12, fontWeight: '700', opacity: 0.8 },
  reactRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, paddingVertical: 2 },
  reactPctCol: { minWidth: 92 },
  reactLine: { fontSize: 12 },
  reactPctVal: { fontWeight: '800' },
  reactHorizon: { fontSize: 11, opacity: 0.6 },
  reactGoldClosed: { fontSize: 11, opacity: 0.55 },
  reactCtx: { fontSize: 11, opacity: 0.7, flex: 1 },
});
