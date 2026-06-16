/**
 * CosmicPolymarket — marchés prédictifs en « barres de probabilité » (γ, bout 6).
 *
 * Chaque marché de seuil = une barre remplie à la probabilité implicite (argent
 * en jeu). Remplace la carte thémée `PolymarketCard`. Données réelles (snapshot
 * shadow). CONTEXTE, pas un signal (Axe #1).
 */

import { useMemo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Cosmic } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import type { PolymarketSnapshot } from '@/src/api/types';

interface Props {
  snapshot: PolymarketSnapshot | null;
  entityId: string;
  onEntityChange?: (entityId: string) => void;
  loading?: boolean;
  error?: string | null;
  displayLimit?: number;
}

const ENTITIES = ['BTC', 'GOLD'] as const;

function probColor(p: number): string {
  if (p >= 0.6) return Cosmic.long;
  if (p >= 0.4) return Cosmic.neutral;
  return Cosmic.short;
}

/** 'YYYY-MM-DD...' → 'DD/MM/YY' (échéance du marché). */
function fmtDue(iso: string | null): string | null {
  if (!iso) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}/${m[2]}/${m[1].slice(2)}` : null;
}

export function CosmicPolymarket({
  snapshot,
  entityId,
  onEntityChange,
  loading,
  error,
  displayLimit = 6,
}: Props) {
  const markets = useMemo(() => {
    if (!snapshot) return [];
    return snapshot.events
      .flatMap((e) => e.markets.map((m) => ({ ...m, end_date: e.end_date })))
      .filter((m) => m.yes_prob != null && m.question)
      .sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0))
      .slice(0, displayLimit);
  }, [snapshot, displayLimit]);

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Marchés prédictifs</Text>
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
        <Text style={styles.empty}>Indisponible : {error}</Text>
      ) : loading && markets.length === 0 ? (
        <Text style={styles.empty}>Chargement…</Text>
      ) : markets.length === 0 ? (
        <Text style={styles.empty}>Pas de marché prédictif {entityId} récent.</Text>
      ) : (
        markets.map((m, i) => {
          const p = m.yes_prob ?? 0;
          const color = probColor(p);
          return (
            <View key={`${m.clob_token_id ?? m.question}-${i}`} style={styles.row}>
              <View style={styles.qRow}>
                <Text style={styles.question} numberOfLines={1}>
                  {m.question}
                </Text>
                {fmtDue(m.end_date) ? (
                  <Text style={styles.due}>éch. {fmtDue(m.end_date)}</Text>
                ) : null}
              </View>
              <View style={styles.barRow}>
                <View style={styles.track}>
                  <View
                    style={[styles.fill, { width: `${Math.round(p * 100)}%`, backgroundColor: color }]}
                  />
                </View>
                <Text style={[styles.pct, { color }]}>{Math.round(p * 100)}%</Text>
              </View>
            </View>
          );
        })
      )}

      <Text style={styles.note}>
        Probabilités implicites des paris (argent en jeu) à atteindre AVANT l&apos;échéance —
        horizon swing, contexte.
      </Text>
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
    gap: 10,
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
  toggle: { flexDirection: 'row', gap: 4 },
  tog: {
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: Cosmic.borderStrong,
  },
  togActive: { backgroundColor: Cosmic.accent, borderColor: Cosmic.accent },
  togText: { color: Cosmic.textDim, fontSize: 11, fontWeight: '700' },
  togTextActive: { color: Cosmic.bgDeep },
  row: { gap: 4 },
  qRow: { flexDirection: 'row', alignItems: 'baseline', gap: 8 },
  question: { flex: 1, color: Cosmic.text, fontSize: 13, lineHeight: 17 },
  due: { color: Cosmic.textFaint, fontSize: 10, fontFamily: Fonts.mono },
  barRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  track: {
    flex: 1,
    height: 8,
    borderRadius: 4,
    overflow: 'hidden',
    backgroundColor: 'rgba(255,255,255,0.06)',
  },
  fill: { height: '100%', borderRadius: 4 },
  pct: {
    width: 42,
    textAlign: 'right',
    fontSize: 13,
    fontWeight: '800',
    fontFamily: Fonts.mono,
  },
  note: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontStyle: 'italic',
  },
  empty: {
    color: Cosmic.textDim,
    fontSize: 13,
    paddingVertical: 6,
  },
});
