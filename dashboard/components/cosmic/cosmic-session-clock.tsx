/**
 * Horloge de séances de marché (refonte γ — onglet Macro, bout B 2026-06-19).
 *
 * Répond à la demande « trader au bon moment de la plage horaire » : affiche
 * QUAND chaque grande place (Asie/Tokyo · Europe/Londres · US/New York) est
 * ouverte, quand a lieu le chevauchement Londres–NY (fenêtre la plus liquide),
 * et l'état du marché de l'or (COMEX) + BTC.
 *
 * ⚠️ CONTEXTE / DISCIPLINE, PAS un signal. Toute la logique vient du module pur
 * `src/macro/sessions.ts` (heures de place + heure d'été par règles, sans `Intl`).
 * Rien ici ne touche direction/veracity/combined_bias (NO-GO inchangé).
 */

import { StyleSheet, Text, View } from 'react-native';

import { Cosmic } from '@/constants/cosmic';
import { useTick } from '@/src/hooks/use-tick';
import { computeSessions, type GoldState, type MarketState } from '@/src/macro/sessions';
import { usMarketHolidayName } from '@/src/utils/markets';

function goldColor(state: GoldState): string {
  if (state === 'open') return Cosmic.long;
  if (state === 'pause') return Cosmic.neutral;
  return Cosmic.textFaint;
}

export function CosmicSessionClock() {
  useTick(60_000); // re-render chaque minute pour suivre l'horloge
  const now = new Date();
  const snap = computeSessions(now, usMarketHolidayName(now));

  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>Séances de marché</Text>
        <Text style={styles.utc}>{snap.utcLabel}</Text>
      </View>

      {snap.sessions.map((s) => {
        const open = s.state === ('open' as MarketState);
        return (
          <View key={s.id} style={styles.row}>
            <View style={[styles.dot, { backgroundColor: open ? Cosmic.long : Cosmic.textFaint }]} />
            <Text style={styles.label}>{s.label}</Text>
            <Text style={styles.hours}>{s.hoursUtc}</Text>
            <Text style={[styles.state, { color: open ? Cosmic.long : Cosmic.textFaint }]}>
              {open ? 'ouverte' : 'fermée'}
            </Text>
          </View>
        );
      })}

      {(snap.weekend || snap.dailyLull) && (
        <Text style={styles.hint}>
          {snap.weekend
            ? '🌙 Week-end — forex & or fermés (BTC reste 24/7).'
            : '🌙 Creux quotidien — passage NY → Sydney, liquidité minimale.'}
        </Text>
      )}

      <View
        style={[styles.overlap, { borderColor: snap.overlapActive ? Cosmic.accent : Cosmic.border }]}>
        <Text
          style={[
            styles.overlapText,
            { color: snap.overlapActive ? Cosmic.accent : Cosmic.textDim },
          ]}>
          {snap.overlapActive ? '🔥 ' : ''}Chevauchement Londres–NY · {snap.overlapHoursUtc}
        </Text>
        <Text style={styles.overlapSub}>
          Fenêtre la plus liquide{snap.overlapActive ? ' — active maintenant' : ''}
        </Text>
      </View>

      <View style={styles.assetsRow}>
        <View style={styles.asset}>
          <Text style={styles.assetLabel}>🥇 Or (COMEX)</Text>
          <Text style={[styles.assetState, { color: goldColor(snap.gold.state) }]}>
            {snap.gold.note}
          </Text>
        </View>
        <View style={styles.asset}>
          <Text style={styles.assetLabel}>₿ BTC</Text>
          <Text style={[styles.assetState, { color: Cosmic.long }]}>24/7</Text>
        </View>
      </View>

      <Text style={styles.caveat}>
        Liquidité ≠ direction : ceci indique QUAND le marché bouge le plus, pas dans quel sens.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Cosmic.card,
    borderWidth: 1,
    borderColor: Cosmic.border,
    borderRadius: 16,
    padding: 14,
    gap: 9,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  title: {
    color: Cosmic.text,
    fontSize: 16,
    fontWeight: '700',
  },
  utc: {
    color: Cosmic.accent,
    fontSize: 14,
    fontWeight: '600',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  dot: {
    width: 9,
    height: 9,
    borderRadius: 5,
  },
  label: {
    color: Cosmic.text,
    fontSize: 14,
    flex: 1,
  },
  hours: {
    color: Cosmic.textDim,
    fontSize: 12,
  },
  state: {
    fontSize: 12,
    fontWeight: '600',
    width: 58,
    textAlign: 'right',
  },
  hint: {
    color: Cosmic.macro,
    fontSize: 12,
    fontWeight: '600',
  },
  overlap: {
    marginTop: 2,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 9,
    paddingHorizontal: 11,
    gap: 2,
  },
  overlapText: {
    fontSize: 13,
    fontWeight: '600',
  },
  overlapSub: {
    color: Cosmic.textFaint,
    fontSize: 11,
  },
  assetsRow: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 2,
  },
  asset: {
    flex: 1,
    backgroundColor: Cosmic.bg,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: Cosmic.border,
    paddingVertical: 8,
    paddingHorizontal: 10,
    gap: 2,
  },
  assetLabel: {
    color: Cosmic.textDim,
    fontSize: 12,
  },
  assetState: {
    fontSize: 13,
    fontWeight: '600',
  },
  caveat: {
    color: Cosmic.textFaint,
    fontSize: 11,
    lineHeight: 15,
    fontStyle: 'italic',
    marginTop: 2,
  },
});
