/**
 * Présentation cosmique de l'actualité (refonte γ, bout 6) :
 *   - CosmicHeadlines : dernières actus avec tag BULL/BEAR + sélecteur BTC/GOLD,
 *     date de publication par ligne, et bouton « Voir toutes les actus » qui
 *     NAVIGUE vers la page détail (drill-down, comme l'ancienne carte).
 *   - CosmicBreaking  : bandeau « 🚨 Breaking » (rendu uniquement s'il y a des
 *     items) avec, comme la carte d'avant la refonte : l'âge (source · il y a X),
 *     les RÉACTIONS mesurées BTC + Or (factuel, pas une prédiction), et une
 *     légende « Comment ça peut bouger le BTC et l'or » (mécanisme ↓/↑ par
 *     catégorie présente).
 *
 * 100 % données réelles (Headline[] / BreakingNewsItem[] / BreakingReaction[]).
 * CONTEXTE/alerte, pas un signal directionnel (Axe #1). L'humain interprète.
 */

import { useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { UnavailableState } from './cosmic-unavailable-state';

import { Cosmic } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import type { BreakingNewsItem, BreakingReaction, Headline } from '@/src/api/types';
import { useTick } from '@/src/hooks/use-tick';
import { timeAgo } from '@/src/utils/time';

/** N'ouvre qu'une URL http(s) absolue (garde-fou H3). */
function openUrl(url: string | null) {
  if (url && /^https?:\/\//i.test(url)) void Linking.openURL(url);
}

function sentimentMeta(s: string): { label: string; color: string } {
  if (s === 'bull') return { label: 'BULL', color: Cosmic.long };
  if (s === 'bear') return { label: 'BEAR', color: Cosmic.short };
  return { label: 'NEUTRE', color: Cosmic.neutral };
}

interface CatMeta {
  emoji: string;
  label: string;
  color: string;
  /** Comment cette catégorie peut bouger le BTC (honnête, dans les 2 sens). */
  mechanism: string;
}
const CATEGORY_META: Record<string, CatMeta> = {
  'guerre/géopol': {
    emoji: '🌍',
    label: 'Guerre/géopol',
    color: Cosmic.short,
    mechanism:
      'Escalade → « risk-off », BTC souvent ↓ ; désescalade/accord → appétit du risque, souvent ↑. L’or joue souvent l’inverse (valeur refuge) — effet réel mais inconstant.',
  },
  'politique US': {
    emoji: '🏛️',
    label: 'Politique US',
    color: Cosmic.macro,
    mechanism:
      'Choc fiscal/institutionnel → bouge le dollar & les taux US (dollar fort / taux ↑ = pression ↓ sur BTC ; l’or sensible au dollar et au taux réel).',
  },
  'tarifs/commerce': {
    emoji: '📦',
    label: 'Tarifs/commerce',
    color: Cosmic.neutral,
    mechanism: 'Tarifs / guerre commerciale → inflation + « risk-off » → BTC souvent ↓ à court terme.',
  },
  'Fed/taux/macro': {
    emoji: '🏦',
    label: 'Fed/taux',
    color: Cosmic.neutral,
    mechanism: 'Moteur macro n°1 : Fed « hawkish » / taux ↑ → ↓ ; « dovish » / baisse de taux → ↑.',
  },
  'crypto/régulation': {
    emoji: '⚖️',
    label: 'Crypto/régul',
    color: Cosmic.accent,
    mechanism: 'Effet direct : durcissement / interdiction → ↓ ; feu vert (ETF, cadre clair) → ↑.',
  },
  personnalités: {
    emoji: '🗣️',
    label: 'Personnalités',
    color: Cosmic.macro,
    mechanism:
      'Figure pro-BTC (Saylor, BlackRock, Coinbase…) qui annonce un achat/soutien → lu haussier ↑ (souvent déjà anticipé) ; sortie/critique (Buffett, Schiff, Dimon, régulateur) → pression ↓. Schiff/Dalio = pro-or. À recouper avec le volume réel.',
  },
};
function categoryMeta(c: string): CatMeta {
  return (
    CATEGORY_META[c] ?? { emoji: '📰', label: c || 'Actu', color: Cosmic.textDim, mechanism: '' }
  );
}

/** Couleur d'une réaction mesurée (vert/rouge/neutre, palette douce). */
function reactionColor(pct: number): string {
  if (pct >= 0.5) return Cosmic.long;
  if (pct <= -0.5) return Cosmic.short;
  return Cosmic.textDim;
}

const COLLAPSED_COUNT = 3;

const ENTITIES = ['BTC', 'GOLD'] as const;

interface HeadlinesProps {
  headlines: Headline[];
  entityId: string;
  onEntityChange?: (entityId: string) => void;
  loading?: boolean;
  error?: string | null;
  displayLimit?: number;
  /** Si fourni : affiche un bouton « Voir toutes les actus » qui appelle ce callback (navigation). */
  onSeeAll?: () => void;
}

export function CosmicHeadlines({
  headlines,
  entityId,
  onEntityChange,
  loading,
  error,
  displayLimit = 5,
  onSeeAll,
}: HeadlinesProps) {
  useTick(); // « il y a X » des actus avance en temps réel (30 s)
  const visible = headlines.slice(0, displayLimit);
  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Dernières actus</Text>
        <View style={styles.toggle}>
          {ENTITIES.map((e) => {
            const active = entityId === e;
            return (
              <Pressable
                key={e}
                onPress={() => onEntityChange?.(e)}
                style={[styles.tog, active ? styles.togActive : null]}>
                <Text style={[styles.togText, active ? styles.togTextActive : null]}>{e}</Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      {error ? (
        <UnavailableState kind="error" error={error} />
      ) : loading && visible.length === 0 ? (
        <UnavailableState kind="loading" />
      ) : visible.length === 0 ? (
        <UnavailableState kind="empty" message="Pas d'actu récente." />
      ) : (
        visible.map((h, i) => {
          const sm = sentimentMeta(h.sentiment);
          return (
            <Pressable
              key={`${h.url ?? h.title}-${i}`}
              onPress={() => openUrl(h.url)}
              style={({ pressed }) => [styles.row, { opacity: pressed && h.url ? 0.6 : 1 }]}>
              <View
                style={[styles.pill, { borderColor: sm.color + '66', backgroundColor: sm.color + '1f' }]}>
                <Text style={[styles.pillText, { color: sm.color }]}>{sm.label}</Text>
              </View>
              <View style={styles.rowBody}>
                <Text style={styles.headline} numberOfLines={2}>
                  {h.title}
                </Text>
                <Text style={styles.pub}>
                  {h.publisher} · {timeAgo(h.published_at ?? h.fetched_at)}
                </Text>
              </View>
            </Pressable>
          );
        })
      )}

      {onSeeAll && headlines.length > 0 ? (
        <Pressable onPress={onSeeAll} style={styles.more}>
          <Text style={styles.moreText}>Voir toutes les actus ({headlines.length}) ›</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

interface BreakingProps {
  items: BreakingNewsItem[];
  reactions?: BreakingReaction[];
}

export function CosmicBreaking({ items, reactions = [] }: BreakingProps) {
  useTick(); // âge des breaking (« il y a X ») rafraîchi en temps réel
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) return null;
  const visible = expanded ? items : items.slice(0, COLLAPSED_COUNT);
  const hidden = items.length - visible.length;
  const categoriesPresent = Array.from(new Set(items.map((i) => i.category)));
  return (
    <View style={[styles.card, styles.breakingCard]}>
      <Text style={styles.breakingTitle}>🚨 Breaking</Text>
      <Text style={styles.breakingSub}>
        Alerte / contexte — pas un signal. Vérifie ta position, ne trade pas dans la panique.
      </Text>

      {visible.map((it, i) => {
        const m = categoryMeta(it.category);
        return (
          <Pressable
            key={`${it.url ?? it.title}-${i}`}
            onPress={() => openUrl(it.url)}
            style={({ pressed }) => [styles.brRow, { opacity: pressed && it.url ? 0.6 : 1 }]}>
            <View style={styles.brTopRow}>
              <View style={[styles.brTag, { borderColor: m.color + '66', backgroundColor: m.color + '1f' }]}>
                <Text style={[styles.brTagText, { color: m.color }]}>
                  {m.emoji} {m.label}
                </Text>
              </View>
              <Text style={styles.brMeta}>
                {it.source} · {timeAgo(it.detected_at ?? it.published_at ?? '')}
              </Text>
            </View>
            <Text style={styles.brText} numberOfLines={2}>
              {it.title_fr ?? it.title}
            </Text>
          </Pressable>
        );
      })}

      {hidden > 0 ? (
        <Pressable onPress={() => setExpanded(true)} style={styles.more}>
          <Text style={[styles.moreText, { color: Cosmic.short }]}>Voir les {hidden} autres ›</Text>
        </Pressable>
      ) : expanded && items.length > COLLAPSED_COUNT ? (
        <Pressable onPress={() => setExpanded(false)} style={styles.more}>
          <Text style={[styles.moreText, { color: Cosmic.short }]}>Réduire ‹</Text>
        </Pressable>
      ) : null}

      {/* Réactions mesurées BTC + Or (factuel post-alerte, pas une prédiction) */}
      {reactions.length > 0 ? (
        <View style={styles.reactions}>
          <Text style={styles.reactTitle}>📊 Réactions mesurées BTC + Or (factuel, pas une prédiction)</Text>
          {reactions.map((rx, idx) => (
            <View key={`${rx.alerted_at}-${rx.horizon_h}-${idx}`} style={styles.reactRow}>
              <View style={styles.reactPctCol}>
                <Text style={styles.reactLine}>
                  ₿{' '}
                  <Text style={[styles.reactPctVal, { color: reactionColor(rx.pct) }]}>
                    {rx.pct >= 0 ? '+' : ''}
                    {rx.pct.toFixed(1)}%
                  </Text>{' '}
                  <Text style={styles.reactHorizon}>{rx.horizon_h}h</Text>
                </Text>
                {rx.gold_closed ? (
                  <Text style={styles.reactGoldClosed}>🥇 marché fermé</Text>
                ) : rx.gold_pct != null ? (
                  <Text style={styles.reactLine}>
                    🥇{' '}
                    <Text style={[styles.reactPctVal, { color: reactionColor(rx.gold_pct) }]}>
                      {rx.gold_pct >= 0 ? '+' : ''}
                      {rx.gold_pct.toFixed(1)}%
                    </Text>
                  </Text>
                ) : null}
              </View>
              <Text style={styles.reactCtx} numberOfLines={2}>
                {categoryMeta(rx.category).emoji} {rx.title}
              </Text>
            </View>
          ))}
        </View>
      ) : null}

      {/* Légende : comment chaque catégorie présente peut bouger le BTC et l'or */}
      {categoriesPresent.length > 0 ? (
        <View style={styles.legend}>
          <Text style={styles.legendTitle}>Comment ça peut bouger le BTC et l’or</Text>
          {categoriesPresent.map((cat) => {
            const m = categoryMeta(cat);
            if (!m.mechanism) return null;
            return (
              <Text key={cat} style={styles.legendRow}>
                {m.emoji} <Text style={styles.legendCat}>{m.label}</Text> — {m.mechanism}
              </Text>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
    gap: 8,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  toggle: {
    flexDirection: 'row',
    gap: 4,
  },
  tog: {
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: Cosmic.borderStrong,
  },
  togActive: {
    backgroundColor: Cosmic.accent,
    borderColor: Cosmic.accent,
  },
  togText: {
    color: Cosmic.textDim,
    fontSize: 11,
    fontWeight: '700',
  },
  togTextActive: {
    color: Cosmic.bgDeep,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    paddingVertical: 6,
    borderTopWidth: 1,
    borderTopColor: Cosmic.border,
  },
  pill: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
    marginTop: 1,
  },
  pillText: {
    fontSize: 9,
    fontWeight: '800',
    letterSpacing: 0.5,
    fontFamily: Fonts.mono,
  },
  rowBody: {
    flex: 1,
    gap: 2,
  },
  headline: {
    color: Cosmic.text,
    fontSize: 14,
    lineHeight: 19,
  },
  pub: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontFamily: Fonts.mono,
  },
  empty: {
    color: Cosmic.textDim,
    fontSize: 13,
    paddingVertical: 6,
  },
  breakingCard: {
    borderColor: Cosmic.short + '88',
    backgroundColor: 'rgba(232,122,122,0.07)',
  },
  breakingTitle: {
    color: Cosmic.short,
    fontSize: 14,
    fontWeight: '800',
  },
  breakingSub: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontStyle: 'italic',
    lineHeight: 15,
  },
  brRow: {
    gap: 5,
    paddingVertical: 7,
    borderTopWidth: 1,
    borderTopColor: Cosmic.border,
  },
  brTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    flexWrap: 'wrap',
  },
  brTag: {
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  brTagText: {
    fontSize: 9,
    fontWeight: '800',
    letterSpacing: 0.4,
    fontFamily: Fonts.mono,
  },
  brMeta: {
    color: Cosmic.textFaint,
    fontSize: 10,
    fontFamily: Fonts.mono,
  },
  brText: {
    color: Cosmic.text,
    fontSize: 13,
    lineHeight: 18,
  },
  reactions: {
    marginTop: 2,
    gap: 3,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: Cosmic.border,
  },
  reactTitle: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontWeight: '700',
  },
  reactRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
    paddingVertical: 2,
  },
  reactPctCol: {
    minWidth: 96,
  },
  reactLine: {
    color: Cosmic.textDim,
    fontSize: 12,
  },
  reactPctVal: {
    fontWeight: '800',
    fontFamily: Fonts.mono,
  },
  reactHorizon: {
    color: Cosmic.textFaint,
    fontSize: 11,
  },
  reactGoldClosed: {
    color: Cosmic.textFaint,
    fontSize: 11,
  },
  reactCtx: {
    color: Cosmic.textFaint,
    fontSize: 11,
    flex: 1,
    lineHeight: 15,
  },
  legend: {
    marginTop: 2,
    gap: 4,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: Cosmic.border,
  },
  legendTitle: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontWeight: '700',
  },
  legendRow: {
    color: Cosmic.textFaint,
    fontSize: 11,
    lineHeight: 16,
  },
  legendCat: {
    color: Cosmic.textDim,
    fontWeight: '700',
  },
  more: {
    paddingTop: 8,
    alignItems: 'center',
  },
  moreText: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '700',
  },
});
