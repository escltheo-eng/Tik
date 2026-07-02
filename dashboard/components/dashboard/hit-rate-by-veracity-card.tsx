/**
 * HitRateByVeracityCard — détail du hit rate par tranche d'accord entre sources.
 *
 * Phase A.2-bis trading manuel J+10. Insight critique du backtest 2026-05-05 :
 * le filtre veracity ≥ 0,90 transforme un hit rate perdant (22%) en gagnant
 * (42-67%). Cette carte rend le bénéfice du filtre visible côté dashboard.
 *
 * Carte SOUS HitRateCard, partage les mêmes sélecteurs (entity × horizon) via
 * props. Pas de sélecteurs propres pour économiser la place et éviter la
 * désynchronisation visuelle.
 *
 * Refonte cosmique : View/Text + tokens Cosmic (rendue uniquement dans l'onglet
 * Plus, fond sombre forcé). « veracity » est nommée « accord » côté UI (A9).
 *
 * UX :
 * - 4 lignes (1 par bucket d'accord)
 * - Chaque ligne : label + barre de couleur selon hit rate + N entre parenthèses
 * - Bucket avec N<10 → opacité réduite + warning "échantillon faible"
 * - Bucket vide → grisé total
 *
 * Limites assumées :
 * - Buckets très peu peuplés ont un hit rate volatile
 * - Période bullish/bearish biaise globalement (même filtre)
 */

import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { InfoTooltip } from '@/components/ui/info-tooltip';
import { Cosmic } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
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
  if (empty) return Cosmic.textFaint;
  if (lowSample) return Cosmic.textFaint;
  if (hitRate < 0.5) return Cosmic.short;
  if (hitRate < 0.6) return Cosmic.neutral;
  return Cosmic.long;
}

function BucketRow({ bucket }: { bucket: HitRateByVeracityBucket }) {
  const empty = bucket.n_evaluated === 0;
  const lowSample = !empty && bucket.n_evaluated < MIN_SAMPLE_SIZE;
  const color = bucketColor(bucket.hit_rate, lowSample, empty);
  const barWidth = empty ? 0 : Math.max(bucket.hit_rate * 100, 2); // 2% mini visible

  return (
    <View style={styles.bucketRow}>
      <View style={styles.bucketLabelCol}>
        <Text style={styles.bucketLabel}>accord {bucket.bucket_label}</Text>
        <Text style={styles.bucketMeta}>
          {empty
            ? 'aucun signal'
            : `${bucket.n_success} / ${bucket.n_evaluated} corrects · gain moy ${bucket.avg_gain_pct >= 0 ? '+' : ''}${bucket.avg_gain_pct.toFixed(2)}%`}
        </Text>
        {lowSample ? (
          <Text style={styles.lowSampleLabel}>
            ⚠ échantillon faible (N&lt;{MIN_SAMPLE_SIZE})
          </Text>
        ) : null}
      </View>
      <View style={styles.bucketRateCol}>
        <Text style={[styles.bucketRate, { color }]}>
          {empty ? '—' : `${(bucket.hit_rate * 100).toFixed(0)}%`}
        </Text>
        <View style={styles.barTrack}>
          <View style={[styles.barFill, { width: `${barWidth}%`, backgroundColor: color }]} />
        </View>
      </View>
    </View>
  );
}

export function HitRateByVeracityCard({
  data,
  entityId,
  horizon,
  loading,
  error,
}: HitRateByVeracityCardProps) {
  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <View style={styles.titleRow}>
          <Text style={styles.title}>Hit rate par accord</Text>
          <InfoTooltip entryKey="veracity" />
        </View>
        <Text style={styles.periodLabel}>
          {entityId} · {horizon}
        </Text>
      </View>

      {error ? (
        <Text style={styles.errorText}>Indisponible : {error}</Text>
      ) : loading && !data ? (
        <View style={styles.loading}>
          <ActivityIndicator size="small" color={Cosmic.accent} />
        </View>
      ) : data ? (
        <>
          <View style={styles.bucketsList}>
            {data.buckets.map((b) => (
              <BucketRow key={b.bucket_label} bucket={b} />
            ))}
          </View>

          {data.sample_warning ? (
            <Text style={styles.warningLabel}>⚠ {data.sample_warning}</Text>
          ) : null}

          <Text style={styles.footer}>
            Plus l’accord entre sources est haut, plus Tik est confiant. Filtre clé pour calibrer le
            sizing.
          </Text>
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
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
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  title: {
    color: Cosmic.text,
    fontSize: 15,
    fontWeight: '700',
  },
  periodLabel: {
    color: Cosmic.textFaint,
    fontSize: 12,
    fontFamily: Fonts.mono,
  },
  loading: {
    alignItems: 'center',
    paddingVertical: 16,
  },
  errorText: {
    color: Cosmic.short,
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
    color: Cosmic.text,
    fontSize: 13,
    fontWeight: '600',
  },
  bucketMeta: {
    color: Cosmic.textDim,
    fontSize: 11,
  },
  lowSampleLabel: {
    fontSize: 11,
    color: Cosmic.textFaint,
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
    fontFamily: Fonts.mono,
  },
  barTrack: {
    width: 80,
    height: 4,
    backgroundColor: 'rgba(255,255,255,0.1)',
    borderRadius: 2,
    overflow: 'hidden',
  },
  barFill: {
    height: '100%',
    borderRadius: 2,
  },
  warningLabel: {
    fontSize: 12,
    color: Cosmic.textFaint,
    marginTop: 4,
  },
  footer: {
    color: Cosmic.textFaint,
    fontSize: 11,
    marginTop: 4,
    fontStyle: 'italic',
    lineHeight: 16,
  },
});
