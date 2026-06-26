/**
 * CosmicDerivatives — positionnement dérivés en « bras de fer » (refonte γ, bout 6).
 *
 * Barre tug-of-war Longs (vert) vs Shorts (rouge) + funding rate + open interest.
 * Remplace la carte thémée `DerivativesCard`. Données réelles (snapshot ADR-023).
 * CONTEXTE shadow, pas un signal (Axe #1).
 */

import { StyleSheet, Text, View } from 'react-native';

import { UnavailableState } from './cosmic-unavailable-state';

import { Cosmic } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import type { DerivativesSnapshot } from '@/src/api/types';

interface Props {
  snapshot: DerivativesSnapshot | null;
  loading?: boolean;
  error?: string | null;
}

/** Répartition longs/shorts en % (depuis les comptes, sinon dérivée du ratio). */
function longShortPct(s: DerivativesSnapshot): { long: number; short: number } | null {
  const l = s.long_account_global;
  const sh = s.short_account_global;
  if (l != null && sh != null && l + sh > 0) {
    const t = l + sh;
    return { long: (l / t) * 100, short: (sh / t) * 100 };
  }
  const r = s.long_short_ratio_global;
  if (r != null && r > 0) {
    const long = (r / (1 + r)) * 100;
    return { long, short: 100 - long };
  }
  return null;
}

function fundingLabel(f: number | null): string {
  if (f == null) return '—';
  return `${f >= 0 ? '+' : ''}${(f * 100).toFixed(3)} %`;
}

function oiLabel(usd: number | null): string {
  if (usd == null) return '—';
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)} Md`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(0)} M`;
  return `$${usd.toFixed(0)}`;
}

export function CosmicDerivatives({ snapshot, loading, error }: Props) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>Positionnement dérivés · BTC</Text>

      {error ? (
        <UnavailableState kind="error" error={error} />
      ) : loading && !snapshot ? (
        <UnavailableState kind="loading" />
      ) : !snapshot ? (
        <UnavailableState kind="empty" message="Aucune donnée dérivés (snapshot shadow pas encore publié)." />
      ) : (
        <>
          {(() => {
            const ls = longShortPct(snapshot);
            if (!ls) return <Text style={styles.empty}>Ratio long/short indisponible.</Text>;
            return (
              <View style={styles.tugWrap}>
                <View style={styles.tugTrack}>
                  <View style={[styles.tugLong, { flex: Math.max(ls.long, 1) }]} />
                  <View style={[styles.tugShort, { flex: Math.max(ls.short, 1) }]} />
                </View>
                <View style={styles.tugLabels}>
                  <Text style={[styles.tugLabel, { color: Cosmic.long }]}>
                    Longs {ls.long.toFixed(0)}%
                  </Text>
                  <Text style={[styles.tugLabel, { color: Cosmic.short }]}>
                    {ls.short.toFixed(0)}% Shorts
                  </Text>
                </View>
              </View>
            );
          })()}

          <View style={styles.metricRow}>
            <Text style={styles.metricLabel}>Funding rate</Text>
            <Text
              style={[
                styles.metricValue,
                {
                  color:
                    snapshot.funding_rate == null
                      ? Cosmic.text
                      : snapshot.funding_rate >= 0
                        ? Cosmic.long
                        : Cosmic.short,
                },
              ]}>
              {fundingLabel(snapshot.funding_rate)}
            </Text>
          </View>
          <View style={styles.metricRow}>
            <Text style={styles.metricLabel}>Open interest</Text>
            <Text style={styles.metricValue}>{oiLabel(snapshot.open_interest_usd)}</Text>
          </View>

          <Text style={styles.note}>
            Funding {'>'} 0 = les longs paient (foule longue) ; {'<'} 0 = les shorts paient. Contexte,
            pas un signal.
          </Text>
        </>
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
    padding: 14,
    gap: 10,
  },
  title: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  tugWrap: { gap: 6 },
  tugTrack: {
    flexDirection: 'row',
    height: 18,
    borderRadius: 9,
    overflow: 'hidden',
    backgroundColor: 'rgba(255,255,255,0.06)',
  },
  tugLong: { backgroundColor: Cosmic.long },
  tugShort: { backgroundColor: Cosmic.short },
  tugLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  tugLabel: {
    fontSize: 13,
    fontWeight: '800',
    fontFamily: Fonts.mono,
  },
  metricRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
  },
  metricLabel: { color: Cosmic.textDim, fontSize: 13 },
  metricValue: {
    color: Cosmic.text,
    fontSize: 14,
    fontWeight: '700',
    fontFamily: Fonts.mono,
  },
  note: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontStyle: 'italic',
    lineHeight: 15,
  },
  empty: {
    color: Cosmic.textDim,
    fontSize: 13,
    paddingVertical: 6,
  },
});
