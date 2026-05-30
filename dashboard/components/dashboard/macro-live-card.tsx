/**
 * MacroLiveCard — bandeau « ticker » Bloomberg macro (couche optionnelle).
 *
 * Se cale sur le calendrier réel :
 *   - état B (priorité) : un event HIGH/MEDIUM vient de tomber (≤48h) →
 *     affiche le mouvement RÉEL BTC/OR depuis l'heure de l'annonce.
 *   - état A : prochain event imminent (≤24h) → compte à rebours + one-liner.
 *   - sinon : `return null` (carte invisible — pas de pollution visuelle).
 *
 * Mouvement BRUT (pas isolé à la surprise, pas de consensus dispo).
 * Pure couche de contexte/culture — aucun edge revendiqué.
 *
 * Pour retirer : enlever l'import + le rendu dans `app/(tabs)/index.tsx` et
 * supprimer ce fichier + `useMacroReadingLive.ts` + `getMacroReadingLive` +
 * les types `MacroLive*`. Backend côté `/macro_reading/live` peut rester (ne
 * sert rien sans consommateur) ou être retiré (cf. memory
 * `macro-reading-educational-layer`).
 */

import { useMemo } from 'react';
import { StyleSheet } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { MacroLiveOut } from '@/src/api/types';
import { useTick } from '@/src/hooks/use-tick';
import { parseUtcIso, timeAgo, timeUntil } from '@/src/utils/time';

export interface MacroLiveCardProps {
  live: MacroLiveOut | null;
  loading?: boolean;
  error?: string | null;
}

// Fenêtre du « DANS X » : on n'affiche le compte à rebours que si l'event est
// imminent (≤24h). Au-delà → silence (la carte « Calendrier macro » s'en charge).
const NEXT_EVENT_WINDOW_H = 24;

function importanceColor(imp: string): string {
  switch (imp) {
    case 'HIGH':
      return '#c0392b';
    case 'MEDIUM':
      return '#e67e22';
    default:
      return '#7f8c8d';
  }
}

function moveColor(v: number | null): string {
  if (v === null) return '#7f8c8d';
  if (v >= 0.5) return '#27ae60';
  if (v <= -0.5) return '#c0392b';
  return '#7f8c8d';
}

function signedPct(v: number | null): string {
  if (v === null) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
}

function hoursUntil(iso: string): number {
  return (parseUtcIso(iso).getTime() - Date.now()) / 3_600_000;
}

export function MacroLiveCard({ live, loading: _loading, error: _error }: MacroLiveCardProps) {
  // `tick` force un re-render minute-aware pour que les « il y a Xmin » / « dans Xmin »
  // restent justes sans re-fetch (cf. fix Bug B `useTick`).
  useTick(60_000);

  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];

  // Priorité : event récent (actionnable maintenant) > event imminent > rien.
  const mode = useMemo<'recent' | 'next' | null>(() => {
    if (!live) return null;
    if (live.recent_event) return 'recent';
    if (live.next_event && hoursUntil(live.next_event.scheduled_for) <= NEXT_EVENT_WINDOW_H)
      return 'next';
    return null;
  }, [live]);

  if (!live || mode === null) return null;

  // Ne pas afficher d'erreur visible : la carte est silencieuse par design.
  // (l'erreur réseau est gérée — pas de carte d'erreur qui prendrait de la place).

  if (mode === 'recent' && live.recent_event) {
    const ev = live.recent_event;
    const impColor = importanceColor(ev.importance);
    return (
      <ThemedView style={[styles.card, { borderColor: impColor, borderLeftWidth: 4 }]}>
        <ThemedView style={[styles.headerRow, { backgroundColor: 'transparent' }]}>
          <ThemedView style={[styles.impDot, { backgroundColor: impColor }]} />
          <ThemedText style={[styles.statusLabel, { color: impColor }]}>
            ● IL Y A {timeAgo(ev.scheduled_for)}
          </ThemedText>
          <ThemedText style={styles.importanceTag}>{ev.importance}</ThemedText>
        </ThemedView>

        <ThemedText type="defaultSemiBold" style={styles.eventName}>
          {ev.event_name}
        </ThemedText>
        <ThemedText style={styles.oneLiner}>{ev.one_liner}</ThemedText>

        <ThemedView style={[styles.movesRow, { backgroundColor: 'transparent' }]}>
          <ThemedView style={[styles.moveBlock, { backgroundColor: 'transparent' }]}>
            <ThemedText style={styles.moveLabel}>BTC</ThemedText>
            <ThemedText style={[styles.moveValue, { color: moveColor(ev.btc_move_pct) }]}>
              {signedPct(ev.btc_move_pct)}
            </ThemedText>
          </ThemedView>
          <ThemedView style={[styles.moveBlock, { backgroundColor: 'transparent' }]}>
            <ThemedText style={styles.moveLabel}>OR</ThemedText>
            <ThemedText style={[styles.moveValue, { color: moveColor(ev.gold_move_pct) }]}>
              {signedPct(ev.gold_move_pct)}
            </ThemedText>
          </ThemedView>
        </ThemedView>

        <ThemedText style={[styles.footer, { color: palette.icon }]}>
          Mouvement BRUT depuis l&apos;annonce · pas isolé à la surprise · contexte
        </ThemedText>
      </ThemedView>
    );
  }

  // mode === 'next'
  const ev = live.next_event!;
  const impColor = importanceColor(ev.importance);
  return (
    <ThemedView style={[styles.card, { borderColor: impColor, borderLeftWidth: 4 }]}>
      <ThemedView style={[styles.headerRow, { backgroundColor: 'transparent' }]}>
        <ThemedView style={[styles.impDot, { backgroundColor: impColor }]} />
        <ThemedText style={[styles.statusLabel, { color: impColor }]}>
          📅 {timeUntil(ev.scheduled_for).toUpperCase()}
        </ThemedText>
        <ThemedText style={styles.importanceTag}>{ev.importance}</ThemedText>
      </ThemedView>

      <ThemedText type="defaultSemiBold" style={styles.eventName}>
        {ev.event_name}
      </ThemedText>
      <ThemedText style={styles.oneLiner}>{ev.one_liner}</ThemedText>

      <ThemedText style={[styles.footer, { color: palette.icon }]}>
        Discipline ±4h autour des HIGH (Garde-fou 2-bis)
      </ThemedText>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 12, padding: 14, gap: 6 },
  headerRow: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  impDot: { width: 8, height: 8, borderRadius: 4 },
  statusLabel: { fontSize: 12, fontWeight: '700', letterSpacing: 0.4 },
  importanceTag: {
    fontSize: 10,
    fontWeight: '700',
    opacity: 0.6,
    marginLeft: 'auto',
    letterSpacing: 0.4,
  },
  eventName: { fontSize: 15, marginTop: 2 },
  oneLiner: { fontSize: 13, opacity: 0.85, lineHeight: 18 },
  movesRow: { flexDirection: 'row', gap: 24, marginTop: 6 },
  moveBlock: { gap: 2 },
  moveLabel: { fontSize: 11, opacity: 0.6, fontWeight: '700', letterSpacing: 0.4 },
  moveValue: { fontSize: 18, fontWeight: '700', fontVariant: ['tabular-nums'] },
  footer: { fontSize: 10, opacity: 0.6, fontStyle: 'italic', marginTop: 4 },
});
