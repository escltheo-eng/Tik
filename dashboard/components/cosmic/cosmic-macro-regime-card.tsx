/**
 * CosmicMacroRegimeCard — port cosmique de `MacroRegimeCard` (ADR-028, CONTEXTE).
 *
 * Mêmes données (prop `regime`) et même logique d'affichage que la carte thémée ;
 * seul le rendu passe en palette γ (fond sombre). CONTEXTE STRICT : ces chiffres
 * FRED ne touchent jamais direction/veracity/combined_bias. On AFFICHE des séries
 * datées, on n'AFFIRME rien (cf. « Lecture macro » retirée le 2026-05-30).
 */

import { StyleSheet, Text, View } from 'react-native';

import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import type { MacroIndicator, MacroRegime } from '@/src/api/types';

export interface CosmicMacroRegimeCardProps {
  regime: MacroRegime | null;
  loading?: boolean;
  error?: string | null;
}

// Fonds de badge un peu saturés pour rester lisibles avec un texte blanc.
const REGIME_BG: Record<string, string> = {
  expansion: '#3fae86',
  contraction: '#d99a3c',
  neutral: '#6b7280',
};
const WARN = Cosmic.neutral; // surlignage « point d'attention » (récession, courbe inversée)

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

function regimeBg(r: string | null): string {
  return REGIME_BG[r ?? ''] ?? '#6b7280';
}

function fmtDelta(busd: number | null): string {
  if (busd == null) return '—';
  return `${busd >= 0 ? '+' : ''}${busd.toFixed(0)} Md$`;
}

export function CosmicMacroRegimeCard({ regime, loading, error }: CosmicMacroRegimeCardProps) {
  const nl = regime?.net_liquidity ?? null;
  const hasData = regime?.available && nl?.available;
  const ind = (key: string): MacroIndicator | null => regime?.indicators?.[key] ?? null;

  const recession = ind('recession_prob_12m');
  const realRate = ind('real_rate_10y');
  const breakeven = ind('breakeven_inflation_10y');
  const curve = ind('curve_2s10s');
  const nfci = ind('financial_conditions_nfci');

  const renderIndicator = (label: string, value: string, note?: string, color?: string) => (
    <View style={styles.metricRow}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={[styles.metricValue, color ? { color } : null]}>
        {value}
        {note ? <Text style={styles.metricNote}> · {note}</Text> : null}
      </Text>
    </View>
  );

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Régime macro</Text>
        <Text style={styles.periodLabel}>FRED · contexte</Text>
      </View>

      <Text style={styles.disclaimer}>
        Chiffres FRED officiels datés (liquidité Fed, taux réels, récession) — contexte, pas un
        signal Tik.
      </Text>

      {error ? (
        <Text style={styles.errorText}>Indisponible : {error}</Text>
      ) : loading && !regime ? (
        <Text style={styles.emptyLabel}>Chargement…</Text>
      ) : !hasData ? (
        <Text style={styles.emptyLabel}>
          {"Aucune donnée collectée (l'ingester n'a pas encore publié)."}
        </Text>
      ) : (
        <View style={styles.body}>
          {/* Fed Net Liquidity — bloc mis en avant */}
          <View style={styles.netliqBlock}>
            <View style={styles.netliqHead}>
              <Text style={styles.netliqTitle}>Fed Net Liquidity</Text>
              <View style={[styles.badge, { backgroundColor: regimeBg(nl!.regime) }]}>
                <Text style={styles.badgeText}>{regimeLabel(nl!.regime)}</Text>
              </View>
            </View>
            <Text style={styles.netliqValue}>
              {nl!.net_liquidity_tusd != null ? `${nl!.net_liquidity_tusd.toFixed(2)} T$` : '—'}
              <Text style={styles.metricNote}>
                {'  '}Δ13 sem {fmtDelta(nl!.delta_13w_busd)}
                {nl!.zscore_52w != null ? ` · z ${nl!.zscore_52w.toFixed(2)}` : ''}
              </Text>
            </Text>
            <Text style={styles.interpretation}>
              Liquidité $ disponible pour les actifs risqués (bilan Fed − cash Trésor − reverse
              repo). Historiquement porteuse en hausse — contexte, pas une prédiction.
            </Text>
          </View>

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

          {nl!.as_of ? <Text style={styles.asof}>Net liquidity au {nl!.as_of}</Text> : null}
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
    color: Cosmic.textDim,
    fontSize: 13,
  },
  netliqValue: {
    color: Cosmic.text,
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
    color: '#ffffff',
    fontSize: 11,
    fontWeight: '600',
  },
  metricRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  metricLabel: {
    color: Cosmic.textDim,
    fontSize: 13,
  },
  metricValue: {
    color: Cosmic.text,
    fontSize: 14,
    fontWeight: '600',
    fontVariant: ['tabular-nums'],
  },
  metricNote: {
    color: Cosmic.textFaint,
    fontSize: 12,
    fontWeight: '400',
  },
  interpretation: {
    color: Cosmic.textDim,
    fontSize: 12,
    lineHeight: 17,
  },
  asof: {
    color: Cosmic.textFaint,
    fontSize: 11,
    marginTop: 2,
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
