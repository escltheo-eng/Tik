/**
 * CosmicSignalRow — ligne d'un signal dans la liste Signals (refonte γ).
 *
 * Port cosmique de la ligne de l'ancien onglet Signals : actif, sens, horizon,
 * badges anti-fake-news / proximité macro, métriques labellisées (conv/verac/
 * sources/amplitude), + tag « court terme indécis » (flash BTC haché). Un tap
 * ouvre la page détail (drill-down).
 */

import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { AntiFakeNewsBadge } from '@/components/dashboard/anti-fake-news-badge';
import { NearMacroBadge } from '@/components/dashboard/near-macro-badge';
import { Cosmic, directionMeta } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import type { Signal } from '@/src/api/types';
import { formatAmplitudePct, horizonLabel } from '@/src/utils/amplitude';
import { timeAgo } from '@/src/utils/time';

interface Props {
  signal: Signal;
  showChoppy?: boolean;
  onChoppyPress?: () => void;
}

export function CosmicSignalRow({ signal, showChoppy, onChoppyPress }: Props) {
  const router = useRouter();
  const dir = directionMeta(signal.direction);

  return (
    <Pressable
      onPress={() => router.push(`/signal/${encodeURIComponent(signal.id)}`)}
      style={({ pressed }) => [styles.row, { opacity: pressed ? 0.65 : 1 }]}>
      {/* Ligne 1 : sens + actif + horizon + badges + heure */}
      <View style={styles.line}>
        <View
          style={[
            styles.tag,
            { backgroundColor: dir.color + '22', borderColor: dir.color + '66' },
          ]}>
          <Text style={[styles.tagText, { color: dir.color }]}>{dir.label}</Text>
        </View>
        <Text style={styles.entity}>{signal.entity_id}</Text>
        <Text style={styles.meta}>{horizonLabel(signal.horizon)}</Text>
        <AntiFakeNewsBadge status={signal.circuit_breaker_status} compact />
        {signal.advisory?.near_macro_event ? (
          <NearMacroBadge data={signal.advisory.near_macro_event} compact />
        ) : null}
        <View style={styles.spacer} />
        <Text style={styles.time}>{timeAgo(signal.timestamp)}</Text>
        <Text style={styles.chevron}>›</Text>
      </View>

      {/* Ligne 2 : métriques labellisées */}
      <View style={styles.metricsLine}>
        <Text style={styles.metric}>conv {(signal.confidence * 100).toFixed(0)}%</Text>
        <Text style={styles.metricSep}>·</Text>
        <Text style={styles.metric}>accord {(signal.veracity * 100).toFixed(0)}%</Text>
        <Text style={styles.metricSep}>·</Text>
        <Text style={styles.metric}>{signal.sources_count} sources</Text>
        {signal.advisory?.expected_amplitude_pct ? (
          <>
            <Text style={styles.metricSep}>·</Text>
            <Text style={styles.metric}>
              ±{formatAmplitudePct(signal.advisory.expected_amplitude_pct)}%
            </Text>
          </>
        ) : null}
      </View>

      {/* Tag « court terme indécis » (flash BTC haché) */}
      {showChoppy ? (
        <Pressable onPress={onChoppyPress} hitSlop={6} style={styles.choppyWrap}>
          <Text style={styles.choppyTag}>🔀 court terme indécis</Text>
        </Pressable>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 11,
    paddingHorizontal: 12,
    marginBottom: 8,
    gap: 7,
  },
  line: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
  },
  tag: {
    borderWidth: 1,
    borderRadius: 7,
    paddingVertical: 3,
    paddingHorizontal: 8,
    minWidth: 62,
    alignItems: 'center',
  },
  tagText: {
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  entity: {
    color: Cosmic.text,
    fontSize: 15,
    fontWeight: '700',
  },
  meta: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontFamily: Fonts.mono,
  },
  spacer: { flex: 1 },
  time: {
    color: Cosmic.textFaint,
    fontSize: 11,
  },
  chevron: {
    color: Cosmic.textDim,
    fontSize: 20,
    marginLeft: 2,
  },
  metricsLine: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 5,
  },
  metric: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontFamily: Fonts.mono,
  },
  metricSep: {
    color: Cosmic.textFaint,
    fontSize: 12,
  },
  choppyWrap: {
    alignSelf: 'flex-start',
  },
  choppyTag: {
    fontSize: 10,
    fontWeight: '700',
    color: '#a79bff',
    backgroundColor: 'rgba(125, 116, 230, 0.18)',
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: 6,
    overflow: 'hidden',
  },
});
