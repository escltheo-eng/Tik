/**
 * NearMacroBadge — repère de discipline « event macro HIGH proche » (Phase B1.5).
 *
 * Posé par le backend (scoring/macro_proximity.py) dans
 * `Signal.advisory.near_macro_event` quand le signal a été émis dans la
 * fenêtre ±4h d'un événement macro HIGH (NFP, CPI, FOMC, BCE, BoJ…) impactant
 * son entité. Sert la discipline Garde-fou 2-bis : ne pas entrer en swing dans
 * les ±4h autour d'un event HIGH, ou sizing divisé par 2 (0,5 %).
 *
 * Couleur AMBRE 📅 — volontairement distincte de l'anti-fake-news (orange/rouge,
 * désaccord de sources SUR un signal) et du repère flash « court terme indécis »
 * (indigo 🔀, direction qui change DANS LE TEMPS). Trois concepts différents.
 *
 * 2 modes :
 * - `compact` (liste Signals) : pastille « 📅 {code} » tap → Alert explicatif.
 * - défaut (détail signal) : carte avec date, proximité, rappel de discipline,
 *   tap → calendrier macro.
 *
 * N'influence PAS la décision (ADR-017 : le calendrier est un outil de
 * discipline humain, pas un input des engines).
 */

import { useRouter } from 'expo-router';
import { Alert, Pressable, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import type { NearMacroEvent } from '@/src/api/types';
import { formatLocal } from '@/src/utils/time';

const AMBER = '#b7791f';
const AMBER_SOFT = 'rgba(183, 121, 31, 0.12)';

export interface NearMacroBadgeProps {
  data: NearMacroEvent;
  /** Mode compact pour la liste Signals (pastille seule). */
  compact?: boolean;
}

function fmtDuration(hoursAbs: number): string {
  const totalMin = Math.round(hoursAbs * 60);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h <= 0) return `${m} min`;
  if (m === 0) return `${h} h`;
  return `${h} h ${m} min`;
}

/** Phrase relative à l'émission : « émis ~2 h avant NFP » / « ~1 h après ». */
function proximityPhrase(data: NearMacroEvent): string {
  const dur = fmtDuration(Math.abs(data.hours_until));
  const sens = data.hours_until >= 0 ? 'avant' : 'après';
  return `émis ~${dur} ${sens} ${data.event_code}`;
}

const DISCIPLINE_NOTE =
  'Règle ±4h (Garde-fou 2-bis) : ne pas entrer en swing dans la fenêtre, ou ' +
  'sizing divisé par 2 (0,5 %). Forte volatilité attendue autour de l’événement.';

export function NearMacroBadge({ data, compact }: NearMacroBadgeProps) {
  const router = useRouter();

  if (compact) {
    const onPress = () => {
      Alert.alert(
        `Event macro proche : ${data.event_code}`,
        `${data.title} (${data.importance})\n${proximityPhrase(data)}.\n\n${DISCIPLINE_NOTE}`,
        [{ text: 'OK', style: 'default' }],
      );
    };
    return (
      <Pressable
        onPress={onPress}
        hitSlop={6}
        accessibilityRole="button"
        accessibilityLabel={`Event macro ${data.event_code} proche — appuyer pour la discipline`}>
        <View style={[styles.compactBadge, { backgroundColor: AMBER }]}>
          <ThemedText style={styles.compactLabel}>📅 {data.event_code}</ThemedText>
        </View>
      </Pressable>
    );
  }

  return (
    <Pressable
      onPress={() => router.push('/macro')}
      accessibilityRole="button"
      accessibilityLabel="Voir le calendrier macro">
      <ThemedView style={[styles.fullBadge, { backgroundColor: AMBER_SOFT, borderColor: AMBER }]}>
        <ThemedText style={[styles.fullLabel, { color: AMBER }]}>
          📅 Discipline macro — {data.event_code} ({data.importance})
        </ThemedText>
        <ThemedText style={styles.fullLine}>
          {formatLocal(data.scheduled_for)} · {proximityPhrase(data)}
        </ThemedText>
        <ThemedText style={styles.fullDescription}>{DISCIPLINE_NOTE}</ThemedText>
        <ThemedText style={styles.hint}>Appuyer pour voir le calendrier macro ›</ThemedText>
      </ThemedView>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  compactBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  compactLabel: {
    color: '#ffffff',
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  fullBadge: {
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    marginTop: 4,
    gap: 4,
  },
  fullLabel: {
    fontWeight: '700',
    fontSize: 13,
  },
  fullLine: {
    fontSize: 12,
    fontWeight: '600',
  },
  fullDescription: {
    fontSize: 12,
    opacity: 0.85,
  },
  hint: {
    fontSize: 11,
    opacity: 0.6,
    marginTop: 2,
  },
});
