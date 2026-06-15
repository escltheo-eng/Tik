/**
 * RateProbabilitiesCard — anticipations de taux Fed par réunion (ADR-029, CONTEXTE).
 *
 * Reproduit le « flagship » de centralbank.watch : probabilité de maintien /
 * hausse / baisse à chaque réunion FOMC, déduite des prix des futures Fed Funds
 * (méthodo CME FedWatch). C'est l'ANTICIPATION DU MARCHÉ (argent en jeu), pas un
 * signal Tik : ces probabilités ne touchent jamais direction/veracity/combined_bias.
 *
 * Lecture pour le trading manuel : une réunion proche à ~100 % maintien = peu de
 * surprise attendue ; une bascule vers « hausse » plus probable = resserrement
 * anticipé (historiquement vent contraire pour les actifs risqués). Contexte, pas
 * une prédiction de prix.
 */

import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { RateMeeting, RateProbabilities } from '@/src/api/types';

export interface RateProbabilitiesCardProps {
  rates: RateProbabilities | null;
  loading?: boolean;
  error?: string | null;
  displayLimit?: number;
}

const HOLD = '#7f8c8d'; // gris — maintien
const HIKE = '#e67e22'; // orange — hausse (restrictif)
const CUT = '#27ae60'; // vert — baisse (assouplissement)

function fmtDate(iso: string): string {
  // 'YYYY-MM-DD' -> 'DD/MM'
  const parts = iso.split('-');
  return parts.length === 3 ? `${parts[2]}/${parts[1]}` : iso;
}

function dominant(m: RateMeeting): { label: string; color: string; prob: number } {
  const hold = m.hold ?? 0;
  const hike = m.hike ?? 0;
  const cut = m.cut ?? 0;
  if (hold >= hike && hold >= cut) return { label: 'maintien', color: HOLD, prob: hold };
  if (hike >= cut) return { label: 'hausse', color: HIKE, prob: hike };
  return { label: 'baisse', color: CUT, prob: cut };
}

export function RateProbabilitiesCard({
  rates,
  loading,
  error,
  displayLimit = 5,
}: RateProbabilitiesCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];

  const hasData = rates?.available && (rates.meetings?.length ?? 0) > 0;
  const meetings = (rates?.meetings ?? []).slice(0, displayLimit);

  const renderMeeting = (m: RateMeeting) => {
    const dom = dominant(m);
    const cut = (m.cut ?? 0) * 100;
    const hold = (m.hold ?? 0) * 100;
    const hike = (m.hike ?? 0) * 100;
    return (
      <ThemedView
        key={m.date}
        style={[styles.meetingRow, { backgroundColor: 'transparent' }]}>
        <ThemedText style={styles.meetingDate}>{fmtDate(m.date)}</ThemedText>
        <View style={styles.barTrack}>
          {cut > 0.5 ? <View style={[styles.seg, { width: `${cut}%`, backgroundColor: CUT }]} /> : null}
          {hold > 0.5 ? <View style={[styles.seg, { width: `${hold}%`, backgroundColor: HOLD }]} /> : null}
          {hike > 0.5 ? <View style={[styles.seg, { width: `${hike}%`, backgroundColor: HIKE }]} /> : null}
        </View>
        <ThemedText style={[styles.meetingVerdict, { color: dom.color }]}>
          {dom.label} {Math.round(dom.prob * 100)}%
        </ThemedText>
      </ThemedView>
    );
  };

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Anticipations taux Fed</ThemedText>
        <ThemedText style={styles.periodLabel}>marché · contexte</ThemedText>
      </ThemedView>

      <ThemedText style={styles.disclaimer}>
        Probabilités implicites des futures Fed Funds (méthodo CME FedWatch) —
        anticipation du marché, pas un signal Tik.
      </ThemedText>

      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : loading && !rates ? (
        <ThemedText style={styles.emptyLabel}>Chargement…</ThemedText>
      ) : !hasData ? (
        <ThemedText style={styles.emptyLabel}>
          Aucune donnée collectée (l&apos;ingester n&apos;a pas encore publié).
        </ThemedText>
      ) : (
        <ThemedView style={[styles.body, { backgroundColor: 'transparent' }]}>
          {rates?.current_range ? (
            <ThemedText style={styles.currentRange}>
              Taux cible actuel : {rates.current_range.replace('-', '–')} %
            </ThemedText>
          ) : null}

          <ThemedView style={[styles.legend, { backgroundColor: 'transparent' }]}>
            <ThemedView style={[styles.legendItem, { backgroundColor: 'transparent' }]}>
              <View style={[styles.dot, { backgroundColor: CUT }]} />
              <ThemedText style={styles.legendText}>baisse</ThemedText>
            </ThemedView>
            <ThemedView style={[styles.legendItem, { backgroundColor: 'transparent' }]}>
              <View style={[styles.dot, { backgroundColor: HOLD }]} />
              <ThemedText style={styles.legendText}>maintien</ThemedText>
            </ThemedView>
            <ThemedView style={[styles.legendItem, { backgroundColor: 'transparent' }]}>
              <View style={[styles.dot, { backgroundColor: HIKE }]} />
              <ThemedText style={styles.legendText}>hausse</ThemedText>
            </ThemedView>
          </ThemedView>

          {meetings.map(renderMeeting)}
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
  body: {
    gap: 8,
  },
  currentRange: {
    fontSize: 13,
    fontWeight: '600',
    fontVariant: ['tabular-nums'],
  },
  legend: {
    flexDirection: 'row',
    gap: 14,
    marginBottom: 2,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  legendText: {
    fontSize: 11,
    opacity: 0.7,
  },
  meetingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  meetingDate: {
    fontSize: 12,
    width: 44,
    opacity: 0.8,
    fontVariant: ['tabular-nums'],
  },
  barTrack: {
    flex: 1,
    height: 8,
    borderRadius: 4,
    overflow: 'hidden',
    flexDirection: 'row',
    backgroundColor: 'rgba(127,140,141,0.2)',
  },
  seg: {
    height: '100%',
  },
  meetingVerdict: {
    fontSize: 12,
    width: 100,
    textAlign: 'right',
    fontWeight: '600',
    fontVariant: ['tabular-nums'],
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
