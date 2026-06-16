/**
 * CosmicRateProbabilitiesCard — port cosmique de `RateProbabilitiesCard` (ADR-029).
 *
 * Probabilité maintien / hausse / baisse par réunion FOMC (méthodo CME FedWatch).
 * Mêmes données (prop `rates`) que la carte thémée, rendu palette γ. ANTICIPATION
 * DU MARCHÉ, pas un signal Tik : ne touche jamais direction/veracity/combined_bias.
 */

import { StyleSheet, Text, View } from 'react-native';

import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import type { RateMeeting, RateProbabilities } from '@/src/api/types';

export interface CosmicRateProbabilitiesCardProps {
  rates: RateProbabilities | null;
  loading?: boolean;
  error?: string | null;
  displayLimit?: number;
}

const HOLD = '#8693a8'; // gris bleuté — maintien
const HIKE = '#d99a3c'; // ambre — hausse (restrictif)
const CUT = '#3fae86'; // vert — baisse (assouplissement)

function fmtDate(iso: string): string {
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

export function CosmicRateProbabilitiesCard({
  rates,
  loading,
  error,
  displayLimit = 5,
}: CosmicRateProbabilitiesCardProps) {
  const hasData = rates?.available && (rates.meetings?.length ?? 0) > 0;
  const meetings = (rates?.meetings ?? []).slice(0, displayLimit);

  const renderMeeting = (m: RateMeeting) => {
    const dom = dominant(m);
    const cut = (m.cut ?? 0) * 100;
    const hold = (m.hold ?? 0) * 100;
    const hike = (m.hike ?? 0) * 100;
    return (
      <View key={m.date} style={styles.meetingRow}>
        <Text style={styles.meetingDate}>{fmtDate(m.date)}</Text>
        <View style={styles.barTrack}>
          {cut > 0.5 ? <View style={[styles.seg, { width: `${cut}%`, backgroundColor: CUT }]} /> : null}
          {hold > 0.5 ? <View style={[styles.seg, { width: `${hold}%`, backgroundColor: HOLD }]} /> : null}
          {hike > 0.5 ? <View style={[styles.seg, { width: `${hike}%`, backgroundColor: HIKE }]} /> : null}
        </View>
        <Text style={[styles.meetingVerdict, { color: dom.color }]}>
          {dom.label} {Math.round(dom.prob * 100)}%
        </Text>
      </View>
    );
  };

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Anticipations taux Fed</Text>
        <Text style={styles.periodLabel}>marché · contexte</Text>
      </View>

      <Text style={styles.disclaimer}>
        Probabilités implicites des futures Fed Funds (méthodo CME FedWatch) — anticipation du
        marché, pas un signal Tik.
      </Text>

      {error ? (
        <Text style={styles.errorText}>Indisponible : {error}</Text>
      ) : loading && !rates ? (
        <Text style={styles.emptyLabel}>Chargement…</Text>
      ) : !hasData ? (
        <Text style={styles.emptyLabel}>
          {"Aucune donnée collectée (l'ingester n'a pas encore publié)."}
        </Text>
      ) : (
        <View style={styles.body}>
          {rates?.current_range ? (
            <Text style={styles.currentRange}>
              Taux cible actuel : {rates.current_range.replace('-', '–')} %
            </Text>
          ) : null}

          <View style={styles.legend}>
            <View style={styles.legendItem}>
              <View style={[styles.dot, { backgroundColor: CUT }]} />
              <Text style={styles.legendText}>baisse</Text>
            </View>
            <View style={styles.legendItem}>
              <View style={[styles.dot, { backgroundColor: HOLD }]} />
              <Text style={styles.legendText}>maintien</Text>
            </View>
            <View style={styles.legendItem}>
              <View style={[styles.dot, { backgroundColor: HIKE }]} />
              <Text style={styles.legendText}>hausse</Text>
            </View>
          </View>

          {meetings.map(renderMeeting)}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 14,
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
  title: {
    ...TitleShadow.soft,
    fontFamily: serifTitleFamily,
    color: Cosmic.text,
    fontSize: 16,
    fontWeight: '700',
  },
  periodLabel: {
    color: Cosmic.textFaint,
    fontSize: 12,
  },
  disclaimer: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontStyle: 'italic',
  },
  body: {
    gap: 8,
  },
  currentRange: {
    color: Cosmic.textDim,
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
    color: Cosmic.textFaint,
    fontSize: 11,
  },
  meetingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  meetingDate: {
    color: Cosmic.textDim,
    fontSize: 12,
    width: 44,
    fontVariant: ['tabular-nums'],
  },
  barTrack: {
    flex: 1,
    height: 8,
    borderRadius: 4,
    overflow: 'hidden',
    flexDirection: 'row',
    backgroundColor: 'rgba(255,255,255,0.08)',
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
    color: Cosmic.textDim,
    fontSize: 13,
    paddingVertical: 8,
  },
  errorText: {
    color: Cosmic.short,
    fontSize: 13,
  },
});
