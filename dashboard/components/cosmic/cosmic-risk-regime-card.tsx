/**
 * CosmicRiskRegimeCard — régime de RISQUE objectif (ADR-030, CONTEXTE strict).
 *
 * Affiche le « thermomètre » de risque des marchés : VIX (volatilité implicite du
 * S&P 500) + spreads de crédit (surcoût de taux payé par les entreprises risquées,
 * High Yield & Investment Grade), tous depuis FRED (gratuit). Une jauge demi-cercle
 * montre le centile de stress (vs la dernière année) ; un label dit l'état
 * (calme / neutre / stress élevé).
 *
 * Honnêteté (Axe #1 / ADR-030) : ces chiffres FRED datés ne touchent JAMAIS
 * direction/veracity/combined_bias. `risk_state` décrit l'ENVIRONNEMENT de risque,
 * PAS une prédiction du prix BTC/GOLD (le macro ne prédit pas le BTC — mesuré le
 * 2026-06-19). On affiche des séries objectives, on n'affirme rien sur le sens.
 */

import { StyleSheet, Text, View } from 'react-native';

import { UnavailableState } from './cosmic-unavailable-state';

import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import type { RiskRegime, RiskSeries } from '@/src/api/types';
import { useTick } from '@/src/hooks/use-tick';
import { timeAgo } from '@/src/utils/time';

import { CosmicGauge } from './cosmic-gauge';

export interface CosmicRiskRegimeCardProps {
  risk: RiskRegime | null;
  loading?: boolean;
  error?: string | null;
}

interface StateMeta {
  label: string;
  color: string;
}

function stateMeta(s: string | null): StateMeta {
  switch (s) {
    case 'risk_off':
      return { label: 'Stress élevé', color: Cosmic.short };
    case 'risk_on':
      return { label: 'Marché calme', color: Cosmic.long };
    case 'neutral':
      return { label: 'Risque neutre', color: Cosmic.neutral };
    default:
      return { label: '—', color: Cosmic.textFaint };
  }
}

function pctRankLabel(s: RiskSeries | null): string | null {
  if (!s || s.pct_rank_1y == null) return null;
  return `centile ${Math.round(s.pct_rank_1y * 100)}% / 1 an`;
}

function fmtDelta20d(s: RiskSeries | null, suffix: string): string | null {
  if (!s || s.delta_20d == null) return null;
  return `Δ1 mois ${s.delta_20d >= 0 ? '+' : ''}${s.delta_20d.toFixed(2)}${suffix}`;
}

export function CosmicRiskRegimeCard({ risk, loading, error }: CosmicRiskRegimeCardProps) {
  useTick(); // fraîcheur « il y a X » rafraîchie en temps réel
  const hasData = risk?.available;
  const meta = stateMeta(risk?.risk_state ?? null);
  const vix = risk?.vix ?? null;
  const hy = risk?.hy_oas ?? null;
  const ig = risk?.ig_oas ?? null;

  const renderRow = (label: string, value: string, note?: string | null, color?: string) => (
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
        <Text style={styles.title}>Régime de risque</Text>
        <Text style={styles.periodLabel}>FRED · contexte</Text>
      </View>

      <Text style={styles.disclaimer}>
        VIX + spreads de crédit (le stress des marchés actions & obligataires) — contexte, pas un
        signal Tik. Le macro ne prédit pas le prix du BTC.
      </Text>

      {error ? (
        <UnavailableState kind="error" error={error} />
      ) : loading && !risk ? (
        <UnavailableState kind="loading" />
      ) : !hasData ? (
        <UnavailableState
          kind="empty"
          message="Aucune donnée collectée (l'ingester n'a pas encore publié)."
        />
      ) : (
        <View style={styles.body}>
          {/* Jauge headline : centile de stress (0 = calme, 100% = stress max sur 1 an) */}
          {risk!.stress_percentile != null ? (
            <CosmicGauge
              value={risk!.stress_percentile}
              min={0}
              max={1}
              markerValue={0.5}
              color={meta.color}
              centerLabel={`${Math.round(risk!.stress_percentile * 100)}%`}
              caption={`${meta.label} · centile de stress vs 1 an`}
            />
          ) : (
            <View style={styles.stateRow}>
              <View style={[styles.badge, { backgroundColor: meta.color }]}>
                <Text style={styles.badgeText}>{meta.label}</Text>
              </View>
              <Text style={styles.metricNote}>centile indisponible (historique trop court)</Text>
            </View>
          )}

          {/* État + badge */}
          <View style={styles.stateHead}>
            <Text style={styles.stateTitle}>État du marché</Text>
            <View style={[styles.badge, { backgroundColor: meta.color }]}>
              <Text style={styles.badgeText}>{meta.label}</Text>
            </View>
          </View>

          {vix?.value != null
            ? renderRow(
                'VIX (volatilité)',
                vix.value.toFixed(1),
                [pctRankLabel(vix), fmtDelta20d(vix, '')].filter(Boolean).join(' · ') || undefined,
              )
            : null}
          {hy?.value != null
            ? renderRow(
                'Spread haut rendement',
                `${hy.value.toFixed(2)}%`,
                pctRankLabel(hy) ?? undefined,
                hy.pct_rank_1y != null && hy.pct_rank_1y >= 0.7 ? Cosmic.short : undefined,
              )
            : null}
          {ig?.value != null
            ? renderRow('Spread invest. grade', `${ig.value.toFixed(2)}%`, pctRankLabel(ig) ?? undefined)
            : null}

          <Text style={styles.interpretation}>
            Un spread = le surcoût de taux qu&apos;une entreprise risquée paie vs l&apos;État. Il
            s&apos;écarte quand le marché craint des défauts (stress), se resserre quand tout va bien
            — contexte, pas une prédiction.
          </Text>

          {risk!.as_of ? (
            <Text style={styles.asof}>
              Données au {risk!.as_of} · il y a {timeAgo(risk!.as_of)}
            </Text>
          ) : null}
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
  periodLabel: { color: Cosmic.textFaint, fontSize: 12 },
  disclaimer: { color: Cosmic.textFaint, fontSize: 11, fontStyle: 'italic' },
  body: { gap: 8 },
  stateRow: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  stateHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  stateTitle: { color: Cosmic.textDim, fontSize: 13 },
  badge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 10 },
  badgeText: { color: '#10131c', fontSize: 11, fontWeight: '700' },
  metricRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  metricLabel: { color: Cosmic.textDim, fontSize: 13 },
  metricValue: {
    color: Cosmic.text,
    fontSize: 14,
    fontWeight: '600',
    fontVariant: ['tabular-nums'],
  },
  metricNote: { color: Cosmic.textFaint, fontSize: 12, fontWeight: '400' },
  interpretation: { color: Cosmic.textDim, fontSize: 12, lineHeight: 17 },
  asof: { color: Cosmic.textFaint, fontSize: 11, marginTop: 2 },
  emptyLabel: { color: Cosmic.textDim, fontSize: 13, paddingVertical: 8 },
  errorText: { color: Cosmic.short, fontSize: 13 },
});
