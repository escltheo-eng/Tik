/**
 * PolymarketCard — cotes des marchés prédictifs (SHADOW — contexte de marché).
 *
 * Affiche les probabilités implicites adossées à du vrai argent (« money on the
 * line ») par seuil de prix, pour BTC et GOLD. Utile surtout pour l'OR, léger
 * côté signaux Tik depuis la désactivation DXY/COT (ADR-018 P2).
 *
 * ⚠ Contexte, PAS un signal Tik : ce sont les paris des autres, non validés et
 * non branchés sur le pipeline. À lire à côté de son jugement (cf. NO-GO
 * directionnel + Garde-fou 2-bis : on ne trade pas le GOLD sur les signaux Tik).
 *
 * - Sélecteur BTC/GOLD
 * - Par event (échéance + volume), les seuils les plus INFORMATIFS (proba la plus
 *   proche de 50 % = là où le marché est vraiment incertain), affichés en ordre
 *   de prix. On évite les seuils extrêmes quasi-certains (~0/100 %) qui n'apportent
 *   aucune info, même s'ils concentrent le volume.
 * - Tap sur un event → ouvre la page Polymarket dans le navigateur natif
 */

import { Linking, Pressable, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { PolymarketEvent, PolymarketMarket, PolymarketSnapshot } from '@/src/api/types';
import { timeUntil } from '@/src/utils/time';

export interface PolymarketCardProps {
  snapshot: PolymarketSnapshot | null;
  entityId: string;
  onEntityChange?: (entityId: string) => void;
  entityOptions?: readonly string[];
  /** Nombre d'events affichés (défaut 3). */
  displayLimit?: number;
  /** Nombre de seuils affichés par event (défaut 4, les plus informatifs). */
  marketsPerEvent?: number;
  loading?: boolean;
  error?: string | null;
}

const DEFAULT_ENTITY_OPTIONS = ['BTC', 'GOLD'] as const;

function formatUsd(v: number | null): string {
  if (v == null) return '—';
  return `$${Math.round(v).toLocaleString('en-US')}`;
}

function formatVolume(v: number | null | undefined): string {
  if (!v || v <= 0) return '';
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${Math.round(v / 1_000)}k`;
  return `$${Math.round(v)}`;
}

function formatPct(p: number | null): string {
  if (p == null) return '—';
  const pct = p * 100;
  if (pct > 0 && pct < 1) return '<1%';
  return `${Math.round(pct)}%`;
}

function topMarkets(ev: PolymarketEvent, n: number): PolymarketMarket[] {
  // Les plus informatifs = proba la plus proche de 50 % (marché incertain).
  // Un seuil à 0,5 % ou 99,5 % ne dit rien d'actionnable, même très tradé.
  // On exclut donc le tri par volume (qui remontait du bruit extrême).
  const informative = ev.markets
    .filter((m) => m.yes_prob != null)
    .sort((a, b) => Math.abs((a.yes_prob ?? 0) - 0.5) - Math.abs((b.yes_prob ?? 0) - 0.5))
    .slice(0, n);
  // Affichage en ordre de seuil croissant (lecture naturelle en échelle).
  return informative.sort(
    (a, b) => (a.threshold_usd ?? Infinity) - (b.threshold_usd ?? Infinity),
  );
}

function polymarketUrl(ev: PolymarketEvent): string | null {
  return ev.slug ? `https://polymarket.com/event/${ev.slug}` : null;
}

export function PolymarketCard({
  snapshot,
  entityId,
  onEntityChange,
  entityOptions = DEFAULT_ENTITY_OPTIONS,
  displayLimit = 3,
  marketsPerEvent = 4,
  loading,
  error,
}: PolymarketCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];
  const events = (snapshot?.events ?? []).slice(0, displayLimit);

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Marchés de paris (Polymarket)</ThemedText>
        <ThemedText style={styles.periodLabel}>shadow · contexte</ThemedText>
      </ThemedView>

      <ThemedText style={styles.disclaimer}>
        Probabilités du marché (argent réel) — contexte, pas un signal Tik.
      </ThemedText>

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
                  style={[styles.selectorLabel, { color: active ? '#ffffff' : palette.text }]}>
                  {opt}
                </ThemedText>
              </Pressable>
            );
          })}
        </ThemedView>
      ) : null}

      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : loading && !snapshot ? (
        <ThemedText style={styles.emptyLabel}>Chargement…</ThemedText>
      ) : events.length === 0 ? (
        <ThemedText style={styles.emptyLabel}>
          Aucun marché collecté pour {entityId} (l&apos;ingester n&apos;a pas encore publié).
        </ThemedText>
      ) : (
        <ThemedView style={[styles.list, { backgroundColor: 'transparent' }]}>
          {events.map((ev, idx) => {
            const url = polymarketUrl(ev);
            const markets = topMarkets(ev, marketsPerEvent);
            return (
              <Pressable
                key={`${ev.slug ?? idx}`}
                onPress={() => {
                  if (url) void Linking.openURL(url).catch(() => {});
                }}
                style={({ pressed }) => [
                  styles.eventBlock,
                  { borderBottomColor: palette.icon, opacity: pressed && url ? 0.6 : 1 },
                ]}>
                <ThemedText style={styles.eventTitle} numberOfLines={2}>
                  {ev.title ?? 'Marché'}
                </ThemedText>
                <ThemedText style={styles.eventMeta}>
                  {ev.end_date ? `échéance ${timeUntil(ev.end_date)} · ` : ''}
                  vol {formatVolume(ev.total_volume)}
                </ThemedText>
                {markets.map((m, mIdx) => {
                  const yes = m.yes_prob ?? 0;
                  return (
                    <ThemedView
                      key={`${ev.slug ?? idx}-${mIdx}`}
                      style={[styles.marketRow, { backgroundColor: 'transparent' }]}>
                      <ThemedText style={styles.marketThreshold}>
                        {m.threshold_usd != null ? formatUsd(m.threshold_usd) : (m.question ?? '—')}
                      </ThemedText>
                      <View style={[styles.barTrack, { backgroundColor: palette.icon }]}>
                        <View
                          style={[
                            styles.barFill,
                            { width: `${Math.max(2, Math.min(100, yes * 100))}%` },
                          ]}
                        />
                      </View>
                      <ThemedText style={styles.marketYes}>YES {formatPct(m.yes_prob)}</ThemedText>
                    </ThemedView>
                  );
                })}
              </Pressable>
            );
          })}
        </ThemedView>
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
  eventBlock: {
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 4,
  },
  eventTitle: {
    fontSize: 14,
    lineHeight: 18,
    fontWeight: '600',
  },
  eventMeta: {
    fontSize: 11,
    opacity: 0.65,
    marginBottom: 2,
  },
  marketRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  marketThreshold: {
    fontSize: 12,
    width: 76,
  },
  barTrack: {
    flex: 1,
    height: 6,
    borderRadius: 3,
    overflow: 'hidden',
    opacity: 0.3,
  },
  barFill: {
    height: '100%',
    backgroundColor: '#2980b9',
    borderRadius: 3,
  },
  marketYes: {
    fontSize: 12,
    width: 64,
    textAlign: 'right',
    fontVariant: ['tabular-nums'],
  },
});
