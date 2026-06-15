/**
 * MacroRegimeCard — régime macro objectif (ADR-028, CONTEXTE).
 *
 * Affiche des chiffres FRED officiels datés : Fed Net Liquidity (WALCL−TGA−RRP)
 * et son régime, taux réel 10Y, proba récession 12 m, pente de courbe, conditions
 * financières. Famille de données NON-SENTIMENT (cf. CLAUDE.md §8). Reproduit le
 * menu de centralbank.watch via les sources primaires gratuites (pas de scraping).
 *
 * ⚠ Contexte, PAS un signal Tik : aucune de ces valeurs n'est branchée sur un
 * signal (ne touche jamais direction/veracity/combined_bias). On AFFICHE des
 * séries datées, on n'AFFIRME rien (contraste avec la « Lecture macro » retirée
 * le 2026-05-30). Le label de régime décrit un vent porteur/contraire HISTORIQUE,
 * jamais une prédiction de prix.
 */

import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { MacroIndicator, MacroRegime } from '@/src/api/types';

export interface MacroRegimeCardProps {
  regime: MacroRegime | null;
  loading?: boolean;
  error?: string | null;
}

const GREEN = '#27ae60';
const WARN = '#e67e22';
const NEUTRAL = '#7f8c8d';

function regimeLabel(r: string | null): string {
  switch (r) {
    case 'expansion':
      return 'Liquidité en expansion';
    case 'contraction':
      return 'Liquidité en contraction';
    case 'neutral':
      return 'Liquidité stable';
    default:
      return '—';
  }
}

function regimeColor(r: string | null): string {
  if (r === 'expansion') return GREEN;
  if (r === 'contraction') return WARN;
  return NEUTRAL;
}

function fmtDelta(busd: number | null): string {
  if (busd == null) return '—';
  return `${busd >= 0 ? '+' : ''}${busd.toFixed(0)} Md$`;
}

export function MacroRegimeCard({ regime, loading, error }: MacroRegimeCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];

  const nl = regime?.net_liquidity ?? null;
  const hasData = regime?.available && nl?.available;
  const ind = (key: string): MacroIndicator | null => regime?.indicators?.[key] ?? null;

  const recession = ind('recession_prob_12m');
  const realRate = ind('real_rate_10y');
  const breakeven = ind('breakeven_inflation_10y');
  const curve = ind('curve_2s10s');
  const nfci = ind('financial_conditions_nfci');

  const renderIndicator = (
    label: string,
    value: string,
    note?: string,
    color?: string,
  ) => (
    <ThemedView style={[styles.metricRow, { backgroundColor: 'transparent' }]}>
      <ThemedText style={styles.metricLabel}>{label}</ThemedText>
      <ThemedText style={[styles.metricValue, color ? { color } : null]}>
        {value}
        {note ? <ThemedText style={styles.metricNote}> · {note}</ThemedText> : null}
      </ThemedText>
    </ThemedView>
  );

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Régime macro</ThemedText>
        <ThemedText style={styles.periodLabel}>FRED · contexte</ThemedText>
      </ThemedView>

      <ThemedText style={styles.disclaimer}>
        Chiffres FRED officiels datés (liquidité Fed, taux réels, récession) —
        contexte, pas un signal Tik.
      </ThemedText>

      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : loading && !regime ? (
        <ThemedText style={styles.emptyLabel}>Chargement…</ThemedText>
      ) : !hasData ? (
        <ThemedText style={styles.emptyLabel}>
          Aucune donnée collectée (l&apos;ingester n&apos;a pas encore publié).
        </ThemedText>
      ) : (
        <ThemedView style={[styles.body, { backgroundColor: 'transparent' }]}>
          {/* Fed Net Liquidity — bloc mis en avant */}
          <ThemedView style={[styles.netliqBlock, { backgroundColor: 'transparent' }]}>
            <ThemedView style={[styles.netliqHead, { backgroundColor: 'transparent' }]}>
              <ThemedText style={styles.netliqTitle}>Fed Net Liquidity</ThemedText>
              <View style={[styles.badge, { backgroundColor: regimeColor(nl!.regime) }]}>
                <ThemedText style={styles.badgeText}>{regimeLabel(nl!.regime)}</ThemedText>
              </View>
            </ThemedView>
            <ThemedText style={styles.netliqValue}>
              {nl!.net_liquidity_tusd != null ? `${nl!.net_liquidity_tusd.toFixed(2)} T$` : '—'}
              <ThemedText style={styles.metricNote}>
                {'  '}Δ13 sem {fmtDelta(nl!.delta_13w_busd)}
                {nl!.zscore_52w != null ? ` · z ${nl!.zscore_52w.toFixed(2)}` : ''}
              </ThemedText>
            </ThemedText>
            <ThemedText style={styles.interpretation}>
              Liquidité $ disponible pour les actifs risqués (bilan Fed − cash Trésor
              − reverse repo). Historiquement porteuse en hausse — contexte, pas une
              prédiction.
            </ThemedText>
          </ThemedView>

          {/* Indicateurs de régime */}
          {recession?.value != null
            ? renderIndicator(
                'Proba récession 12 m',
                `${(recession.value * 100).toFixed(0)}%`,
                undefined,
                recession.value >= 0.5 ? WARN : undefined,
              )
            : null}
          {realRate?.value != null
            ? renderIndicator('Taux réel 10Y', `${realRate.value.toFixed(2)}%`)
            : null}
          {breakeven?.value != null
            ? renderIndicator('Inflation anticipée 10Y', `${breakeven.value.toFixed(2)}%`)
            : null}
          {curve?.value != null
            ? renderIndicator(
                'Pente 2s10s',
                `${curve.value >= 0 ? '+' : ''}${curve.value.toFixed(2)}`,
                curve.value < 0 ? 'inversée' : 'positive',
                curve.value < 0 ? WARN : undefined,
              )
            : null}
          {nfci?.value != null
            ? renderIndicator(
                'Conditions fin. (NFCI)',
                nfci.value.toFixed(2),
                nfci.value < 0 ? 'accommodantes' : 'tendues',
              )
            : null}

          {nl!.as_of ? (
            <ThemedText style={styles.asof}>Net liquidity au {nl!.as_of}</ThemedText>
          ) : null}
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
  netliqBlock: {
    gap: 4,
    paddingBottom: 6,
  },
  netliqHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  netliqTitle: {
    fontSize: 13,
    opacity: 0.8,
  },
  netliqValue: {
    fontSize: 18,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
  },
  badgeText: {
    color: '#fff',
    fontSize: 11,
    fontWeight: '600',
  },
  metricRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  metricLabel: {
    fontSize: 13,
    opacity: 0.8,
  },
  metricValue: {
    fontSize: 14,
    fontWeight: '600',
    fontVariant: ['tabular-nums'],
  },
  metricNote: {
    fontSize: 12,
    fontWeight: '400',
    opacity: 0.7,
  },
  interpretation: {
    fontSize: 12,
    opacity: 0.85,
  },
  asof: {
    fontSize: 11,
    opacity: 0.5,
    marginTop: 2,
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
