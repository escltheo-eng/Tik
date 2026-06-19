/**
 * Fenêtres de discipline macro (refonte γ — page Macro, bout D 2026-06-19).
 *
 * Couche « quand NE PAS trader » qui complète l'horloge de séances : prochains
 * events macro HIGH (FOMC, NFP, CPI, BCE, BoJ…) + alerte quand on est dans la
 * fenêtre ±4 h du Garde-fou 2-bis (ne pas entrer en swing, sinon sizing ÷2).
 *
 * Logique pure dans `src/macro/discipline.ts`. Réutilise `useUpcomingMacroEvents`
 * (filtrage HIGH fait côté client pour éviter tout mismatch d'endpoint) + le
 * helper `timeUntil`. Re-render minute via `useTick`.
 *
 * ⚠️ DISCIPLINE / CONTEXTE, PAS un signal : volatilité accrue ≠ prédiction de sens
 * (Axe #1). Ne touche jamais direction/veracity/combined_bias (NO-GO inchangé).
 */

import { StyleSheet, Text, View } from 'react-native';

import { Cosmic } from '@/constants/cosmic';
import { useTick } from '@/src/hooks/use-tick';
import { useUpcomingMacroEvents } from '@/src/hooks/useUpcomingMacroEvents';
import { computeDisciplineState } from '@/src/macro/discipline';
import { formatLocal, timeUntil } from '@/src/utils/time';

export function CosmicDisciplineWindow() {
  useTick(60_000); // re-render chaque minute (compte à rebours + fenêtre ±4 h)
  // Fenêtre large (3 sem.) + filtrage HIGH côté client (cf. discipline.ts).
  const { events, loading, error } = useUpcomingMacroEvents({ hours: 21 * 24, limit: 50 });
  const state = computeDisciplineState(Date.now(), events);

  return (
    <View style={styles.card}>
      <Text style={styles.title}>Fenêtres de discipline</Text>
      <Text style={styles.subtitle}>
        Volatilité accrue autour des events HIGH (FOMC, NFP, CPI, BCE, BoJ…). Garde-fou : ne pas
        entrer en swing à ±4 h — sinon sizing ÷2.
      </Text>

      {error ? (
        <Text style={styles.err}>Indisponible : {error}</Text>
      ) : loading && events.length === 0 ? (
        <Text style={styles.dim}>Chargement…</Text>
      ) : (
        <>
          {state.windowEvent && (
            <View style={styles.danger}>
              <Text style={styles.dangerText}>
                🚫 Zone ±4 h — {state.windowEvent.event.event_name} (
                {timeUntil(state.windowEvent.event.scheduled_for)}). Pas d&apos;entrée swing, sinon
                sizing ÷2.
              </Text>
            </View>
          )}

          {state.upcoming.length === 0 ? (
            <Text style={styles.dim}>Aucun event HIGH dans les 3 prochaines semaines.</Text>
          ) : (
            state.upcoming.map((r) => (
              <View key={`${r.event.event_name}-${r.event.scheduled_for}`} style={styles.row}>
                <View style={styles.rowMain}>
                  <Text style={styles.evName} numberOfLines={1}>
                    {r.event.event_name}
                  </Text>
                  <Text style={styles.evDate}>{formatLocal(r.event.scheduled_for)}</Text>
                </View>
                <Text style={[styles.evWhen, r.inWindow && { color: Cosmic.short }]}>
                  {timeUntil(r.event.scheduled_for)}
                </Text>
              </View>
            ))
          )}
        </>
      )}

      <Text style={styles.caveat}>Discipline (Garde-fou 2-bis), pas une prédiction du sens.</Text>
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
    gap: 8,
  },
  title: {
    color: Cosmic.text,
    fontSize: 16,
    fontWeight: '700',
  },
  subtitle: {
    color: Cosmic.textDim,
    fontSize: 12,
    lineHeight: 17,
  },
  danger: {
    borderWidth: 1,
    borderColor: Cosmic.short,
    borderRadius: 12,
    paddingVertical: 9,
    paddingHorizontal: 11,
    backgroundColor: 'rgba(232,122,122,0.10)',
    marginTop: 2,
  },
  dangerText: {
    color: Cosmic.short,
    fontSize: 13,
    fontWeight: '600',
    lineHeight: 18,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
    paddingVertical: 2,
  },
  rowMain: {
    flex: 1,
    gap: 1,
  },
  evName: {
    color: Cosmic.text,
    fontSize: 14,
    fontWeight: '600',
  },
  evDate: {
    color: Cosmic.textFaint,
    fontSize: 11,
  },
  evWhen: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '600',
  },
  dim: {
    color: Cosmic.textDim,
    fontSize: 13,
    paddingVertical: 4,
  },
  err: {
    color: Cosmic.short,
    fontSize: 13,
  },
  caveat: {
    color: Cosmic.textFaint,
    fontSize: 11,
    lineHeight: 15,
    fontStyle: 'italic',
    marginTop: 2,
  },
});
