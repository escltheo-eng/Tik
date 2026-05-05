/**
 * HitRateByVeracityCard — détail du hit rate par tranche de veracity.
 *
 * Phase A.2-bis trading manuel J+10. Insight critique du backtest 2026-05-05 :
 * le filtre veracity ≥ 0,90 transforme un hit rate perdant (22%) en gagnant
 * (42-67%). Cette carte rend le bénéfice du filtre visible côté dashboard.
 *
 * Carte SOUS HitRateCard, partage les mêmes sélecteurs (entity × horizon) via
 * props. Pas de sélecteurs propres pour économiser la place et éviter la
 * désynchronisation visuelle.
 *
 * UX :
 * - 4 lignes (1 par bucket veracity)
 * - Chaque ligne : label + barre de couleur selon hit rate + N entre parenthèses
 * - Bucket avec N<10 → opacité réduite + warning "échantillon faible"
 * - Bucket vide → grisé total
 *
 * Limites assumées :
 * - Buckets très peu peuplés ont un hit rate volatile
 * - Période bullish/bearish biaise globalement (même filtre)
 */

import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { HitRateByVeracity, HitRateByVeracityBucket } from '@/src/api/types';

const MIN_SAMPLE_SIZE = 10;

export interface HitRateByVeracityCardProps {
  data: HitRateByVeracity | null;
  entityId: string;
  horizon: string;
  loading?: boolean;
  error?: string | null;
}

function bucketColor(hitRate: number, lowSample: boolean, empty: boolean): string {
  if (empty) return '#7f8c8d';
  if (lowSample) return '#95a5a6';
  if (hitRate < 0.5) return '#c0392b';
  if (hitRate < 0.6) return '#e67e22';
  if (hitRate < 0.75) return '#27ae60';
  return '#16a085';
}

function BucketRow({ bucket }: { bucket: HitRateByVeracityBucket }) {
  const empty = bucket.n_evaluated === 0;
  const lowSample = !empty && bucket.n_evaluated < MIN_SAMPLE_SIZE;
  const color = bucketColor(bucket.hit_rate, lowSample, empty);
  const barWidth = empty ? 0 : Math.max(bucket.hit_rate * 100, 2); // 2% mini visible

  return (
    <ThemedView style={[styles.bucketRow, { backgroundColor: 'transparent' }]}>
      <ThemedView style={[styles.bucketLabelCol, { backgroundColor: 'transparent' }]}>
        <ThemedText style={styles.bucketLabel}>veracity {bucket.bucket_label}</ThemedText>
        <ThemedText style={styles.bucketMeta}>
          {empty
            ? 'aucun signal'
            : `${bucket.n_success} / ${bucket.n_evaluated} corrects · gain moy ${bucket.avg_gain_pct >= 0 ? '+' : ''}${bucket.avg_gain_pct.toFixed(2)}%`}
        </ThemedText>
        {lowSample ? (
          <ThemedText style={styles.lowSampleLabel}>
            ⚠ échantillon faible (N&lt;{MIN_SAMPLE_SIZE})
          </ThemedText>
        ) : null}
      </ThemedView>
      <ThemedView style={[styles.bucketRateCol, { backgroundColor: 'transparent' }]}>
        <ThemedText style={[styles.bucketRate, { color }]}>
          {empty ? '—' : `${(bucket.hit_rate * 100).toFixed(0)}%`}
        </ThemedText>
        <View style={styles.barTrack}>
          <View style={[styles.barFill, { width: `${barWidth}%`, backgroundColor: color }]} />
        </View>
      </ThemedView>
    </ThemedView>
  );
}

export function HitRateByVeracityCard({
  data,
  entityId,
  horizon,
  loading,
  error,
}: HitRateByVeracityCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Hit rate par veracity</ThemedText>
        <ThemedText style={styles.periodLabel}>
          {entityId} · {horizon}
        </ThemedText>
      </ThemedView>

      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : loading && !data ? (
        <ThemedView style={[styles.loading, { backgroundColor: 'transparent' }]}>
          <ActivityIndicator size="small" />
        </ThemedView>
      ) : data ? (
        <>
          <ThemedView style={[styles.bucketsList, { backgroundColor: 'transparent' }]}>
            {data.buckets.map((b) => (
              <BucketRow key={b.bucket_label} bucket={b} />
            ))}
          </ThemedView>

          {data.sample_warning ? (
            <ThemedText style={styles.warningLabel}>⚠ {data.sample_warning}</ThemedText>
          ) : null}

          <ThemedText style={styles.footer}>
            Plus la veracity est haute, plus Tik est confiant. Filtre clé pour calibrer le sizing.
          </ThemedText>
        </>
      ) : null}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 10,
    marginTop: 16,
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
  loading: {
    alignItems: 'center',
    paddingVertical: 16,
  },
  errorText: {
    color: '#c0392b',
    fontSize: 13,
  },
  bucketsList: {
    gap: 12,
    marginTop: 4,
  },
  bucketRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  bucketLabelCol: {
    flex: 1,
    gap: 1,
  },
  bucketLabel: {
    fontSize: 13,
    fontWeight: '600',
  },
  bucketMeta: {
    fontSize: 11,
    opacity: 0.7,
  },
  lowSampleLabel: {
    fontSize: 11,
    opacity: 0.7,
    color: '#7f8c8d',
    fontStyle: 'italic',
  },
  bucketRateCol: {
    minWidth: 90,
    alignItems: 'flex-end',
    gap: 4,
  },
  bucketRate: {
    fontSize: 22,
    fontWeight: 'bold',
    lineHeight: 26,
  },
  barTrack: {
    width: 80,
    height: 4,
    backgroundColor: 'rgba(127, 140, 141, 0.2)',
    borderRadius: 2,
    overflow: 'hidden',
  },
  barFill: {
    height: '100%',
    borderRadius: 2,
  },
  warningLabel: {
    fontSize: 12,
    color: '#7f8c8d',
    marginTop: 4,
  },
  footer: {
    fontSize: 11,
    opacity: 0.5,
    marginTop: 4,
    fontStyle: 'italic',
  },
});
