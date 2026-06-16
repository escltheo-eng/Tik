/**
 * Présentation cosmique de l'actualité (refonte γ, bout 6) :
 *   - CosmicHeadlines : dernières actus avec tag BULL/BEAR + sélecteur BTC/GOLD.
 *   - CosmicBreaking  : bandeau « 🚨 Breaking » (rendu uniquement s'il y a des items).
 *
 * 100 % données réelles (Headline[] / BreakingNewsItem[]). Remplace les cartes
 * thémées sur le Cockpit. CONTEXTE/alerte, pas un signal directionnel (Axe #1).
 */

import { useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { Cosmic } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import type { BreakingNewsItem, Headline } from '@/src/api/types';

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
}
const CATEGORY_META: Record<string, CatMeta> = {
  'guerre/géopol': { emoji: '🌍', label: 'Guerre/géopol', color: Cosmic.short },
  'politique US': { emoji: '🏛️', label: 'Politique US', color: Cosmic.macro },
  'tarifs/commerce': { emoji: '📦', label: 'Tarifs/commerce', color: Cosmic.neutral },
  'Fed/taux/macro': { emoji: '🏦', label: 'Fed/taux', color: Cosmic.neutral },
  'crypto/régulation': { emoji: '⚖️', label: 'Crypto/régul', color: Cosmic.accent },
  personnalités: { emoji: '🗣️', label: 'Personnalités', color: Cosmic.macro },
};
function categoryMeta(c: string): CatMeta {
  return CATEGORY_META[c] ?? { emoji: '📰', label: c || 'Actu', color: Cosmic.textDim };
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
}

export function CosmicHeadlines({
  headlines,
  entityId,
  onEntityChange,
  loading,
  error,
  displayLimit = 5,
}: HeadlinesProps) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? headlines : headlines.slice(0, displayLimit);
  const hidden = headlines.length - visible.length;
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
                onPress={() => {
                  setExpanded(false);
                  onEntityChange?.(e);
                }}
                style={[styles.tog, active ? styles.togActive : null]}>
                <Text style={[styles.togText, active ? styles.togTextActive : null]}>{e}</Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      {error ? (
        <Text style={styles.empty}>Actus indisponibles : {error}</Text>
      ) : loading && visible.length === 0 ? (
        <Text style={styles.empty}>Chargement…</Text>
      ) : visible.length === 0 ? (
        <Text style={styles.empty}>Pas d&apos;actu récente.</Text>
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
                <Text style={styles.pub}>{h.publisher}</Text>
              </View>
            </Pressable>
          );
        })
      )}

      {hidden > 0 ? (
        <Pressable onPress={() => setExpanded(true)} style={styles.more}>
          <Text style={styles.moreText}>Voir les {hidden} autres ›</Text>
        </Pressable>
      ) : expanded && headlines.length > displayLimit ? (
        <Pressable onPress={() => setExpanded(false)} style={styles.more}>
          <Text style={styles.moreText}>Réduire ‹</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

interface BreakingProps {
  items: BreakingNewsItem[];
}

export function CosmicBreaking({ items }: BreakingProps) {
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) return null;
  const visible = expanded ? items : items.slice(0, COLLAPSED_COUNT);
  const hidden = items.length - visible.length;
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
            <View style={[styles.brTag, { borderColor: m.color + '66', backgroundColor: m.color + '1f' }]}>
              <Text style={[styles.brTagText, { color: m.color }]}>
                {m.emoji} {m.label}
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
  brText: {
    color: Cosmic.text,
    fontSize: 13,
    lineHeight: 18,
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
