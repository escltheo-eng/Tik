/**
 * HitRatePersoCard — affiche le hit rate personnel de l'utilisatrice
 * (ratio signaux confirmés sur le total des résolus) avec disclaimer
 * « biais de sélection » si l'échantillon est petit.
 *
 * Phase C Session 2 trading manuel J+10 (Paquet 20).
 *
 * Décisions structurantes (cf. CLAUDE.md Paquet 20 D5-D6) :
 *   - D5 : on affiche **toujours** même avec N petit, avec un disclaimer
 *     visible si N<MIN_RELIABLE_N. Transparence pour débutante — voir le
 *     chiffre même petit aide la calibration mentale.
 *   - D6 : placement dans l'onglet Watchlist uniquement (pas Home), pour
 *     garder dans le contexte sémantique.
 *
 * Définition du hit rate perso :
 *   hits = entries avec outcome === 'confirmed'
 *   denominator = entries avec outcome ∈ {'confirmed', 'refuted'}
 *   (n_a et pending sont exclus du dénominateur — soit pas évaluable, soit
 *    pas encore évalué)
 *
 * Important : le hit rate perso ≠ Tik global parce que :
 *   1. Sélection biaisée (vous n'avez suivi que les signaux qui vous
 *      semblaient bons → biais positif probable)
 *   2. Échantillon souvent petit comparé aux centaines de signaux que Tik
 *      émet (visible dans la carte HitRate de l'écran Home)
 *
 * Le disclaimer mentionne ces 2 points.
 */

import { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { WatchlistEntry } from '@/src/watchlist/WatchlistContext';

const MIN_RELIABLE_N = 20;

interface Props {
  entries: WatchlistEntry[];
}

interface PersoStats {
  hits: number;
  denominator: number;
  hitRatePct: number | null;
}

function computePersoStats(entries: WatchlistEntry[]): PersoStats {
  let hits = 0;
  let denominator = 0;
  for (const e of entries) {
    if (e.outcome === 'confirmed') {
      hits += 1;
      denominator += 1;
    } else if (e.outcome === 'refuted') {
      denominator += 1;
    }
    // pending + n_a : exclus du dénominateur
  }
  const hitRatePct = denominator > 0 ? (hits / denominator) * 100 : null;
  return { hits, denominator, hitRatePct };
}

function hitRateColor(pct: number | null): string {
  if (pct === null) return '#7f8c8d';
  if (pct >= 50) return '#27ae60';
  if (pct >= 30) return '#e67e22';
  return '#c0392b';
}

export function HitRatePersoCard({ entries }: Props) {
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];
  const stats = useMemo(() => computePersoStats(entries), [entries]);

  // Pas de carte si jamais aucun signal résolu (réduit le bruit visuel).
  if (stats.denominator === 0) {
    return null;
  }

  const color = hitRateColor(stats.hitRatePct);
  const isReliable = stats.denominator >= MIN_RELIABLE_N;

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <View style={styles.header}>
        <ThemedText type="defaultSemiBold">Hit rate perso</ThemedText>
        <ThemedText style={styles.subtitle}>
          ratio confirmés sur signaux résolus
        </ThemedText>
      </View>
      <View style={styles.statsLine}>
        <ThemedText style={[styles.bigNumber, { color }]}>
          {stats.hitRatePct !== null ? `${stats.hitRatePct.toFixed(0)} %` : '—'}
        </ThemedText>
        <ThemedText style={styles.fraction}>
          {stats.hits} / {stats.denominator} signaux confirmés
        </ThemedText>
      </View>
      {!isReliable ? (
        <View style={[styles.disclaimerBox, { borderColor: '#e67e22' }]}>
          <ThemedText style={styles.disclaimerText}>
            ⚠ Échantillon petit (n={stats.denominator} {'<'} {MIN_RELIABLE_N}). Ce chiffre est
            <ThemedText type="defaultSemiBold"> peu fiable</ThemedText> statistiquement.
            Il reflète aussi un <ThemedText type="defaultSemiBold">biais de sélection</ThemedText> :
            vous n&apos;avez suivi que les signaux qui vous semblaient bons.
            À mettre en perspective avec le hit rate global Tik sur la carte Home.
          </ThemedText>
        </View>
      ) : (
        <ThemedText style={styles.helperText}>
          À comparer avec le hit rate global Tik (carte Home) — votre sélection peut
          être biaisée par les signaux qui vous ont semblé bons au moment du suivi.
        </ThemedText>
      )}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    gap: 8,
  },
  header: {
    gap: 2,
  },
  subtitle: {
    fontSize: 11,
    opacity: 0.6,
    textTransform: 'uppercase',
    letterSpacing: 0.3,
  },
  statsLine: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 10,
  },
  bigNumber: {
    fontSize: 32,
    fontWeight: '700',
  },
  fraction: {
    fontSize: 13,
    opacity: 0.8,
  },
  disclaimerBox: {
    borderWidth: 1,
    borderRadius: 6,
    padding: 8,
    backgroundColor: 'rgba(230, 126, 34, 0.05)',
  },
  disclaimerText: {
    fontSize: 12,
    lineHeight: 17,
  },
  helperText: {
    fontSize: 12,
    opacity: 0.7,
    lineHeight: 16,
  },
});
