/**
 * HitRateCard — carte Home affichant le hit rate live des signaux Tik.
 *
 * Phase A.2 trading manuel J+10. Calibration empirique de la confiance
 * avant de prendre une décision réelle. Réutilise la logique du backtest
 * via l'endpoint `/api/v1/metrics/hit_rate` (cache Redis 15 min côté serveur).
 *
 * - Sélecteur horizon (flash 1h / swing 5j / macro 30j)
 * - Sélecteur entity (BTC / GOLD)
 * - Affichage hit rate % en gros, code couleur (rouge/orange/vert)
 * - Sous-titre : `n_success / n_evaluated · gain moy ±%`
 * - Toggle « Inclure flagués » pour audit (default OFF)
 * - Badge échantillon faible (n < 30) en gris
 * - Bandeau anti-surconfiance : si Tik ne bat pas le pari constant ("robot
 *   bête" : toujours long/short/neutral) sur les mêmes signaux, affiche un
 *   avertissement honnête. Disparaît automatiquement (data.beats_baseline)
 *   quand Tik a un avantage démontré (≥ 5 pts, ≥ 30 signaux).
 *
 * Limites assumées (cf. backend) :
 * - Coûts de transaction non comptés (spread, fees, slippage)
 * - Horizon de mesure fixe par sémantique (swing = 5j, flash = 1h)
 * - Sur fenêtre fortement trending, des baselines naïfs peuvent battre Tik
 */

import { ActivityIndicator, Pressable, StyleSheet } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { HitRate } from '@/src/api/types';

export interface HitRateCardProps {
  /** Données fetchées (null si pas encore chargé). */
  data: HitRate | null;
  /** Entity sélectionnée. */
  entityId: string;
  /** Horizon sélectionné. */
  horizon: string;
  /** Inclure les signaux flagués anti fake-news ? */
  includeFlagged: boolean;
  /** Callbacks de changement. */
  onEntityChange?: (entity: string) => void;
  onHorizonChange?: (horizon: string) => void;
  onIncludeFlaggedChange?: (include: boolean) => void;
  /** Choix possibles. */
  entityOptions?: readonly string[];
  horizonOptions?: readonly string[];
  loading?: boolean;
  error?: string | null;
}

const DEFAULT_ENTITY_OPTIONS = ['BTC', 'GOLD'] as const;
const DEFAULT_HORIZON_OPTIONS = ['flash', 'swing', 'macro'] as const;

const HORIZON_LABEL: Record<string, string> = {
  flash: 'Flash',
  swing: 'Swing',
  macro: 'Macro',
};

const HORIZON_MEASURE_LABEL: Record<string, string> = {
  flash: '1h',
  swing: '5j',
  macro: '30j',
};

function hitRateColor(rate: number, isLowSample: boolean): string {
  if (isLowSample) return '#7f8c8d';
  if (rate < 0.5) return '#c0392b';
  if (rate < 0.6) return '#e67e22';
  if (rate < 0.75) return '#27ae60';
  return '#16a085';
}

/** Libellé FR du pari constant ("robot bête") pour le bandeau anti-surconfiance. */
function baselineLabelFr(label?: string | null): string {
  if (label === 'long') return 'toujours miser à la hausse';
  if (label === 'short') return 'toujours miser à la baisse';
  if (label === 'neutral') return 'toujours rester à l’écart';
  return 'toujours parier pareil';
}

export function HitRateCard({
  data,
  entityId,
  horizon,
  includeFlagged,
  onEntityChange,
  onHorizonChange,
  onIncludeFlaggedChange,
  entityOptions = DEFAULT_ENTITY_OPTIONS,
  horizonOptions = DEFAULT_HORIZON_OPTIONS,
  loading,
  error,
}: HitRateCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];

  const isLowSample = data ? data.n_evaluated > 0 && data.n_evaluated < 30 : false;
  const hasNoData = data ? data.n_evaluated === 0 : false;
  const rateColor = data ? hitRateColor(data.hit_rate, isLowSample || hasNoData) : palette.icon;

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Hit rate live</ThemedText>
        <ThemedText style={styles.periodLabel}>
          {data ? `${data.since_days}j · ${includeFlagged ? 'tous signaux' : 'non flagués'}` : '—'}
        </ThemedText>
      </ThemedView>

      {/* Sélecteur horizon */}
      {onHorizonChange ? (
        <ThemedView style={[styles.selector, { backgroundColor: 'transparent' }]}>
          {horizonOptions.map((opt) => {
            const active = opt === horizon;
            return (
              <Pressable
                key={opt}
                onPress={() => onHorizonChange(opt)}
                style={({ pressed }) => [
                  styles.selectorBtn,
                  {
                    backgroundColor: active ? palette.tint : 'transparent',
                    borderColor: palette.icon,
                    opacity: pressed ? 0.7 : 1,
                  },
                ]}>
                <ThemedText
                  style={[
                    styles.selectorLabel,
                    { color: active ? '#ffffff' : palette.text },
                  ]}>
                  {HORIZON_LABEL[opt] ?? opt} · {HORIZON_MEASURE_LABEL[opt] ?? '—'}
                </ThemedText>
              </Pressable>
            );
          })}
        </ThemedView>
      ) : null}

      {/* Sélecteur entity */}
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
                  style={[
                    styles.selectorLabel,
                    { color: active ? '#ffffff' : palette.text },
                  ]}>
                  {opt}
                </ThemedText>
              </Pressable>
            );
          })}
        </ThemedView>
      ) : null}

      {/* Corps */}
      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : loading && !data ? (
        <ThemedView style={[styles.loading, { backgroundColor: 'transparent' }]}>
          <ActivityIndicator size="small" />
        </ThemedView>
      ) : data ? (
        <>
          <ThemedView style={[styles.rateRow, { backgroundColor: 'transparent' }]}>
            <ThemedText style={[styles.rateValue, { color: rateColor }]}>
              {hasNoData ? '—' : `${(data.hit_rate * 100).toFixed(0)}%`}
            </ThemedText>
            <ThemedView style={[styles.rateMeta, { backgroundColor: 'transparent' }]}>
              <ThemedText style={styles.rateSubtitle}>
                {hasNoData
                  ? 'Aucun signal évalué'
                  : `${data.n_success} corrects / ${data.n_evaluated} signaux`}
              </ThemedText>
              {!hasNoData && (
                <ThemedText style={styles.rateSubtitle}>
                  gain moy {data.avg_gain_pct >= 0 ? '+' : ''}
                  {data.avg_gain_pct.toFixed(2)}%
                </ThemedText>
              )}
            </ThemedView>
          </ThemedView>

          {/* Bandeau anti-surconfiance : visible tant que Tik ne bat pas le pari
              constant ("robot bête"). Disparaît automatiquement quand beats_baseline
              devient vrai (Tik a alors un avantage démontré). */}
          {!hasNoData && data.best_baseline_hit_rate != null && !data.beats_baseline ? (
            <ThemedView style={styles.honestyBanner}>
              <ThemedText style={styles.honestyText}>
                ⚠ Ce taux suit surtout la tendance. Sur les mêmes signaux,{' '}
                {baselineLabelFr(data.best_baseline_label)} aurait fait{' '}
                {(data.best_baseline_hit_rate * 100).toFixed(0)}%. Tik n’a pas (encore)
                d’avantage démontré — ne te fie pas au % seul.
              </ThemedText>
            </ThemedView>
          ) : null}

          {data.sample_warning ? (
            <ThemedText style={styles.warningLabel}>⚠ {data.sample_warning}</ThemedText>
          ) : null}

          {data.n_skipped > 0 ? (
            <ThemedText style={styles.metaInfo}>
              {data.n_skipped} signal(aux) ignoré(s) (prix non disponible)
            </ThemedText>
          ) : null}

          {!includeFlagged && data.n_flagged_excluded > 0 ? (
            <ThemedText style={styles.metaInfo}>
              {data.n_flagged_excluded} flagué(s) anti fake-news exclu(s)
            </ThemedText>
          ) : null}

          {/* Toggle inclure flagués */}
          {onIncludeFlaggedChange ? (
            <Pressable
              onPress={() => onIncludeFlaggedChange(!includeFlagged)}
              style={({ pressed }) => [
                styles.toggleRow,
                { borderColor: palette.icon, opacity: pressed ? 0.7 : 1 },
              ]}>
              <ThemedView
                style={[
                  styles.checkbox,
                  {
                    backgroundColor: includeFlagged ? palette.tint : 'transparent',
                    borderColor: includeFlagged ? palette.tint : palette.icon,
                  },
                ]}>
                {includeFlagged ? <ThemedText style={styles.checkboxMark}>✓</ThemedText> : null}
              </ThemedView>
              <ThemedText style={styles.toggleLabel}>
                Inclure les signaux flagués anti fake-news
              </ThemedText>
            </Pressable>
          ) : null}

          <ThemedText style={styles.footer}>
            Mesure : direction correcte si delta prix sur {HORIZON_MEASURE_LABEL[horizon] ?? '—'}{' '}
            {data.threshold_pct >= 0 ? `≥ ±${data.threshold_pct.toFixed(1)}%` : ''}
            {data.cache_hit ? ' · cache 15 min' : ''}
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
  selector: {
    flexDirection: 'row',
    gap: 6,
    flexWrap: 'wrap',
  },
  selectorBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    borderWidth: 1,
  },
  selectorLabel: {
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 0.2,
  },
  loading: {
    alignItems: 'center',
    paddingVertical: 16,
  },
  errorText: {
    color: '#c0392b',
    fontSize: 13,
  },
  rateRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
    marginTop: 4,
  },
  rateValue: {
    fontSize: 40,
    lineHeight: 48,
    fontWeight: 'bold',
    minWidth: 90,
  },
  rateMeta: {
    flex: 1,
    gap: 2,
  },
  rateSubtitle: {
    fontSize: 13,
    opacity: 0.85,
  },
  warningLabel: {
    fontSize: 12,
    color: '#7f8c8d',
    marginTop: 4,
  },
  honestyBanner: {
    borderWidth: 1,
    borderColor: '#e67e22',
    backgroundColor: 'rgba(230, 126, 34, 0.08)',
    borderRadius: 8,
    padding: 10,
    marginTop: 4,
  },
  honestyText: {
    fontSize: 12,
    lineHeight: 17,
    color: '#b06a1a',
  },
  metaInfo: {
    fontSize: 11,
    opacity: 0.55,
  },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 6,
    paddingHorizontal: 8,
    borderWidth: 1,
    borderRadius: 8,
    marginTop: 4,
  },
  checkbox: {
    width: 18,
    height: 18,
    borderRadius: 4,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxMark: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: 'bold',
    lineHeight: 14,
  },
  toggleLabel: {
    fontSize: 12,
    flex: 1,
  },
  footer: {
    fontSize: 11,
    opacity: 0.5,
    marginTop: 4,
  },
});
