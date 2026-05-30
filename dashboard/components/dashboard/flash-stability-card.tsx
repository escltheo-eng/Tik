/**
 * FlashStabilityCard — stabilité & croisement des sources du flash BTC (onglet Marché).
 *
 * Répond à deux frictions du trading manuel :
 *   1. « Je reçois long puis short en quelques minutes, je ne sais pas quoi prendre »
 *      → verdict de stabilité (CHOPPY / STABLE / INDÉCIS) sur les ~45 dernières min.
 *   2. « Comment croiser les sources davantage »
 *      → carnet d'ordres vs flux agressif côte à côte, avec verdict d'accord/conflit.
 *
 * 100 % calculé côté client depuis les signaux déjà chargés (aucune requête,
 * aucun endpoint, aucun changement moteur). Le flash n'a pas d'edge prouvé :
 * l'objectif est d'aider à NE PAS trader quand c'est instable ou contradictoire.
 */

import { StyleSheet } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Signal } from '@/src/api/types';
import {
  computeFlashStability,
  type Agreement,
  type FlashState,
  type SourceBias,
} from '@/src/flash/stability';
import { useTick } from '@/src/hooks/use-tick';

const STATE_COLOR: Record<FlashState, string> = {
  choppy: '#c0392b',
  stable: '#27ae60',
  indecisive: '#e67e22',
  no_data: '#95a5a6',
};

const BIAS_COLOR: Record<SourceBias, string> = {
  bull: '#27ae60',
  bear: '#c0392b',
  neutral: '#7f8c8d',
  unknown: '#95a5a6',
};

const BIAS_LABEL: Record<SourceBias, string> = {
  bull: 'haussier',
  bear: 'baissier',
  neutral: 'neutre',
  unknown: '—',
};

function dirLabel(direction: string): string {
  if (direction === 'long') return 'LONG';
  if (direction === 'short') return 'SHORT';
  return 'NEUTRE';
}

function verdictLine(state: FlashState, flips: number, window: number, held: number | null): string {
  switch (state) {
    case 'choppy':
      return `⚠ INSTABLE — ${flips} bascules long↔short en ${window} min · reste à l'écart`;
    case 'stable':
      return held != null
        ? `✓ STABLE — direction tenue depuis ${held} min`
        : '✓ STABLE — direction tenue';
    case 'indecisive':
      return '~ INDÉCIS — attends une confirmation avant d\'agir';
    default:
      return 'Pas assez de signaux flash récents';
  }
}

const AGREEMENT_TEXT: Record<Agreement, { label: string; color: string }> = {
  agree: { label: '✓ les 2 sources s\'accordent', color: '#27ae60' },
  conflict: { label: '✗ elles se contredisent — signal peu fiable', color: '#c0392b' },
  partial: { label: '~ accord partiel (une source neutre)', color: '#e67e22' },
  unknown: { label: 'croisement indisponible', color: '#95a5a6' },
};

export function FlashStabilityCard({ signals }: { signals: Signal[] }) {
  // Re-render périodique (30 s) pour garder l'ancienneté de la direction
  // fraîche entre deux refetch. Calcul direct (O(n), trivial) → recomputé à
  // chaque render avec Date.now() courant.
  useTick();
  const stab = computeFlashStability(signals, { entityId: 'BTC', windowMinutes: 45 });

  const headerColor = STATE_COLOR[stab.state];

  return (
    <ThemedView style={[styles.card, { borderColor: headerColor }]}>
      <ThemedView style={styles.header}>
        <ThemedText type="defaultSemiBold">Stabilité flash · BTC</ThemedText>
        <ThemedView style={[styles.dot, { backgroundColor: headerColor }]} />
      </ThemedView>

      <ThemedText style={[styles.verdict, { color: headerColor }]}>
        {verdictLine(stab.state, stab.flips, stab.windowMinutes, stab.directionHeldMinutes)}
      </ThemedText>

      {stab.state !== 'no_data' ? (
        <>
          <ThemedText style={styles.scope}>
            ↑ stabilité de la direction sur les {stab.windowMinutes} dernières minutes
          </ThemedText>
          <ThemedText style={styles.meta}>
            Direction actuelle : {dirLabel(stab.currentDirection)} · {stab.count} signaux /{' '}
            {stab.windowMinutes} min
          </ThemedText>
        </>
      ) : null}

      {stab.cross ? (
        <ThemedView style={styles.crossBox}>
          <ThemedText style={styles.crossTitle}>
            Croisement des 2 sources · à l&apos;instant (dernier signal)
          </ThemedText>

          <ThemedView style={styles.crossRow}>
            <ThemedText style={styles.crossName}>Carnet d&apos;ordres</ThemedText>
            <ThemedText style={[styles.crossBias, { color: BIAS_COLOR[stab.cross.orderbook.bias] }]}>
              {BIAS_LABEL[stab.cross.orderbook.bias]}
              {stab.cross.orderbook.detail ? ` · ${stab.cross.orderbook.detail}` : ''}
            </ThemedText>
          </ThemedView>

          <ThemedView style={styles.crossRow}>
            <ThemedText style={styles.crossName}>Flux agressif</ThemedText>
            <ThemedText style={[styles.crossBias, { color: BIAS_COLOR[stab.cross.aggression.bias] }]}>
              {BIAS_LABEL[stab.cross.aggression.bias]}
              {stab.cross.aggression.detail ? ` · ${stab.cross.aggression.detail}` : ''}
            </ThemedText>
          </ThemedView>

          <ThemedText style={[styles.agreement, { color: AGREEMENT_TEXT[stab.cross.agreement].color }]}>
            {AGREEMENT_TEXT[stab.cross.agreement].label}
          </ThemedText>
        </ThemedView>
      ) : null}

      <ThemedText style={styles.foot}>
        À lire en 2 temps : le verdict = stabilité des {stab.windowMinutes} dernières minutes ; le
        croisement = les 2 sources à l&apos;instant. Idéal pour trader : direction stable ET sources
        d&apos;accord. Flash = court terme bruité, sans edge prouvé — sert surtout à ne PAS trader sur
        du bruit.
      </ThemedText>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: '#888',
    borderRadius: 12,
    padding: 14,
    marginTop: 16,
    gap: 6,
  },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  dot: { width: 12, height: 12, borderRadius: 6 },
  verdict: { fontSize: 14, fontWeight: '700' },
  scope: { fontSize: 11, fontStyle: 'italic', opacity: 0.6 },
  meta: { fontSize: 12, opacity: 0.7 },
  crossBox: {
    marginTop: 4,
    paddingTop: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#888',
    gap: 4,
  },
  crossTitle: { fontSize: 12, fontWeight: '600', opacity: 0.8 },
  crossRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  crossName: { fontSize: 13 },
  crossBias: { fontSize: 13, fontWeight: '600', flexShrink: 1, textAlign: 'right' },
  agreement: { fontSize: 13, fontWeight: '600', marginTop: 2 },
  foot: { fontSize: 11, opacity: 0.6, marginTop: 4 },
});
