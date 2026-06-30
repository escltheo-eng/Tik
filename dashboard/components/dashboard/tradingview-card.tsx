/**
 * TradingViewCard — recommandations techniques TradingView (SHADOW — contexte).
 *
 * Affiche la note technique agrégée de TradingView (Achat fort → Vente forte) pour
 * deux familles :
 * - MACRO : DXY, S&P 500, US 10Y, Or, VIX (en 1D) — le décor macro-éco vu par la
 *   techno ;
 * - MICRO : microstructure de l'actif tradé (BTC ou GOLD) en 5m / 15m / 1h, via un
 *   sélecteur.
 *
 * ⚠ Contexte, PAS un signal Tik : c'est de l'ANALYSE TECHNIQUE (l'avis de l'algo
 * TradingView), que Tik calcule déjà à poids 0 (ADR-018). Ces données ne sont
 * branchées sur aucun signal (shadow strict ADR-031). À lire à côté de son
 * jugement, pas comme un ordre d'achat/vente.
 */

import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { TradingViewItem, TradingViewSnapshot } from '@/src/api/types';

export interface TradingViewCardProps {
  macro: TradingViewSnapshot | null;
  microBtc: TradingViewSnapshot | null;
  microGold: TradingViewSnapshot | null;
  loading?: boolean;
  error?: string | null;
}

const GREEN = '#27ae60';
const RED = '#c0392b';
const GREY = '#7f8c8d';

type MicroEntity = 'BTC' | 'GOLD';

/** Couleur de la note TradingView (achat = vert, vente = rouge, neutre = gris). */
function recoColor(reco: string | null): string {
  if (!reco) return GREY;
  if (reco.includes('BUY')) return GREEN;
  if (reco.includes('SELL')) return RED;
  return GREY;
}

/** Libellé FR de la note TradingView. */
function recoLabel(reco: string | null): string {
  switch (reco) {
    case 'STRONG_BUY':
      return 'Achat fort';
    case 'BUY':
      return 'Achat';
    case 'NEUTRAL':
      return 'Neutre';
    case 'SELL':
      return 'Vente';
    case 'STRONG_SELL':
      return 'Vente forte';
    default:
      return '—';
  }
}

export function TradingViewCard({
  macro,
  microBtc,
  microGold,
  loading,
  error,
}: TradingViewCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];
  const [microEntity, setMicroEntity] = useState<MicroEntity>('BTC');

  const micro = microEntity === 'BTC' ? microBtc : microGold;

  const renderRow = (item: TradingViewItem) => (
    <ThemedView
      key={`${item.symbol}-${item.interval}`}
      style={[styles.row, { backgroundColor: 'transparent' }]}>
      <ThemedText style={styles.rowLabel}>{item.label}</ThemedText>
      <View style={[styles.badge, { backgroundColor: recoColor(item.recommendation) }]}>
        <ThemedText style={styles.badgeText}>{recoLabel(item.recommendation)}</ThemedText>
      </View>
      <ThemedText style={styles.rowCounts}>
        {item.buy ?? '–'}↑ / {item.sell ?? '–'}↓
      </ThemedText>
    </ThemedView>
  );

  const renderBasket = (snap: TradingViewSnapshot | null, emptyLabel: string) => {
    const items = snap?.items ?? [];
    if (items.length === 0) {
      return <ThemedText style={styles.emptyLabel}>{emptyLabel}</ThemedText>;
    }
    return <ThemedView style={[styles.body, { backgroundColor: 'transparent' }]}>{items.map(renderRow)}</ThemedView>;
  };

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Recommandations TradingView</ThemedText>
        <ThemedText style={styles.periodLabel}>shadow · contexte</ThemedText>
      </ThemedView>

      <ThemedText style={styles.disclaimer}>
        Analyse technique (avis de l&apos;algo TradingView) — contexte, pas un signal Tik.
      </ThemedText>

      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : loading && !macro ? (
        <ThemedText style={styles.emptyLabel}>Chargement…</ThemedText>
      ) : (
        <>
          {/* --- Panier MACRO --- */}
          <ThemedText style={styles.sectionTitle}>Macro (journalier)</ThemedText>
          {renderBasket(macro, 'Aucune donnée collectée (l’ingester n’a pas encore publié).')}

          {/* --- Panier MICRO avec bascule BTC / GOLD --- */}
          <ThemedView style={[styles.microHeader, { backgroundColor: 'transparent' }]}>
            <ThemedText style={styles.sectionTitle}>Micro (court terme)</ThemedText>
            <ThemedView style={[styles.selector, { backgroundColor: 'transparent' }]}>
              {(['BTC', 'GOLD'] as MicroEntity[]).map((opt) => {
                const active = opt === microEntity;
                return (
                  <Pressable
                    key={opt}
                    onPress={() => setMicroEntity(opt)}
                    style={({ pressed }) => [
                      styles.selectorBtn,
                      {
                        backgroundColor: active ? palette.tint : 'transparent',
                        borderColor: palette.icon,
                        opacity: pressed ? 0.7 : 1,
                      },
                    ]}>
                    <ThemedText
                      style={[styles.selectorLabel, { color: active ? '#ffffff' : palette.text }]}>
                      {opt}
                    </ThemedText>
                  </Pressable>
                );
              })}
            </ThemedView>
          </ThemedView>
          {renderBasket(micro, 'Aucune donnée collectée pour cet actif.')}
        </>
      )}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 10,
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
  disclaimer: {
    fontSize: 11,
    opacity: 0.6,
    fontStyle: 'italic',
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: '600',
    opacity: 0.85,
    marginTop: 4,
  },
  microHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 6,
  },
  body: {
    gap: 6,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  rowLabel: {
    fontSize: 13,
    width: 84,
    opacity: 0.85,
  },
  badge: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 3,
    borderRadius: 6,
  },
  badgeText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#ffffff',
  },
  rowCounts: {
    fontSize: 12,
    width: 72,
    textAlign: 'right',
    opacity: 0.7,
    fontVariant: ['tabular-nums'],
  },
  selector: {
    flexDirection: 'row',
    gap: 6,
  },
  selectorBtn: {
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 8,
    borderWidth: 1,
  },
  selectorLabel: {
    fontSize: 12,
    fontWeight: '600',
  },
  emptyLabel: {
    opacity: 0.6,
    paddingVertical: 8,
  },
  errorText: {
    color: '#c0392b',
    fontSize: 13,
  },
});
