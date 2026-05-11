/**
 * OverrideOutcomeModal — modal pour redéfinir manuellement l'outcome d'un
 * signal suivi (ex. l'auto-résolution a posé `confirmed` mais l'utilisatrice
 * pense que c'était un faux positif → override `refuted` avec note).
 *
 * Phase C Session 2 trading manuel J+10 (Paquet 20).
 *
 * Décision structurante D7 (cf. CLAUDE.md Paquet 20) :
 *   - Modal avec outcome pré-sélectionné (= valeur courante) + zone de note
 *     libre. Submit → setOutcome local + POST /feedback best-effort
 *     (source='manual').
 *
 * Vocabulaire OSINT-neutre côté UI (cf. Paquet 13 reframe) :
 *   - confirmed = « Confirmé »
 *   - refuted   = « Infirmé »
 *   - n_a       = « Pas évaluable »
 *   - pending   = « En attente » (option de réinitialiser, rare mais utile)
 */

import { useEffect, useState } from 'react';
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useAuth } from '@/src/auth/AuthContext';
import {
  useWatchlist,
  type WatchlistEntry,
  type WatchlistOutcome,
} from '@/src/watchlist/WatchlistContext';
import { submitWatchlistFeedback } from '@/src/watchlist/feedback';

const OUTCOME_CHOICES: { value: WatchlistOutcome; label: string; color: string }[] = [
  { value: 'confirmed', label: 'Confirmé', color: '#27ae60' },
  { value: 'refuted', label: 'Infirmé', color: '#c0392b' },
  { value: 'n_a', label: 'Pas évaluable', color: '#95a5a6' },
  { value: 'pending', label: 'En attente (reset)', color: '#7f8c8d' },
];

interface Props {
  /** Entry à override. Si null, la modale est fermée. */
  entry: WatchlistEntry | null;
  /** Callback appelé après submit OU annulation. Ferme la modale côté parent. */
  onClose: () => void;
}

export function OverrideOutcomeModal({ entry, onClose }: Props) {
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];
  const { client, apiKey } = useAuth();
  const { setOutcome } = useWatchlist();

  const [selected, setSelected] = useState<WatchlistOutcome>('pending');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [feedbackStatus, setFeedbackStatus] = useState<'idle' | 'ok' | 'failed'>('idle');

  // Reset à chaque ouverture (nouveau signal sélectionné).
  useEffect(() => {
    if (entry) {
      setSelected(entry.outcome);
      setNote(entry.userNote ?? '');
      setFeedbackStatus('idle');
      setSubmitting(false);
    }
  }, [entry]);

  if (entry === null) {
    return null;
  }

  const handleSubmit = async () => {
    if (submitting) return;
    setSubmitting(true);

    // 1. Update local immédiat (toujours, même si POST /feedback échoue).
    const noteToStore = note.trim().length > 0 ? note.trim() : null;
    setOutcome(entry.signalId, selected, noteToStore);

    // 2. POST /feedback best-effort (sauf si pending — rien à submit).
    if (selected !== 'pending' && apiKey) {
      const ok = await submitWatchlistFeedback(client, entry.signalId, selected, {
        source: 'manual',
        note: noteToStore,
      });
      setFeedbackStatus(ok ? 'ok' : 'failed');
      // Petit délai pour que l'utilisatrice voie le statut avant fermeture.
      setTimeout(() => {
        setSubmitting(false);
        onClose();
      }, ok ? 600 : 1500);
    } else {
      setSubmitting(false);
      onClose();
    }
  };

  return (
    <Modal
      visible={entry !== null}
      transparent
      animationType="fade"
      onRequestClose={onClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.backdrop}>
        <Pressable
          style={StyleSheet.absoluteFill}
          onPress={onClose}
          accessibilityRole="button"
          accessibilityLabel="Fermer la modal"
        />
        <ThemedView style={[styles.modal, { borderColor: palette.icon }]}>
          <ScrollView
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.modalContent}>
            <View style={styles.header}>
              <ThemedText type="defaultSemiBold" style={styles.title}>
                Modifier le résultat
              </ThemedText>
              <ThemedText style={styles.signalRef}>
                {entry.entityId} · {entry.horizon} · {entry.direction.toUpperCase()}
              </ThemedText>
            </View>

            <View style={styles.section}>
              <ThemedText style={styles.sectionLabel}>Nouveau résultat</ThemedText>
              <View style={styles.outcomeRow}>
                {OUTCOME_CHOICES.map((choice) => {
                  const isSelected = choice.value === selected;
                  return (
                    <Pressable
                      key={choice.value}
                      onPress={() => setSelected(choice.value)}
                      accessibilityRole="button"
                      accessibilityState={{ selected: isSelected }}
                      style={[
                        styles.outcomeBtn,
                        {
                          borderColor: isSelected ? choice.color : palette.icon,
                          backgroundColor: isSelected
                            ? `${choice.color}22`
                            : 'transparent',
                        },
                      ]}>
                      <ThemedText
                        style={[
                          styles.outcomeBtnLabel,
                          { color: isSelected ? choice.color : palette.text },
                        ]}>
                        {choice.label}
                      </ThemedText>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            <View style={styles.section}>
              <ThemedText style={styles.sectionLabel}>
                Note (optionnelle, envoyée au backend pour audit)
              </ThemedText>
              <TextInput
                value={note}
                onChangeText={setNote}
                placeholder="Ex. faux positif à cause d'un event macro non détecté"
                placeholderTextColor={palette.icon}
                multiline
                numberOfLines={3}
                style={[
                  styles.noteInput,
                  { borderColor: palette.icon, color: palette.text },
                ]}
                accessibilityLabel="Note libre sur le résultat"
              />
            </View>

            {feedbackStatus === 'ok' ? (
              <ThemedText style={[styles.statusLine, { color: '#27ae60' }]}>
                ✓ Envoyé au backend (sera pris en compte à la prochaine recalibration daily 03h UTC)
              </ThemedText>
            ) : feedbackStatus === 'failed' ? (
              <ThemedText style={[styles.statusLine, { color: '#e67e22' }]}>
                ⚠ Backend injoignable — résultat enregistré localement uniquement
              </ThemedText>
            ) : null}

            <View style={styles.actions}>
              <Pressable
                onPress={onClose}
                disabled={submitting}
                style={({ pressed }) => [
                  styles.actionBtn,
                  styles.cancelBtn,
                  { borderColor: palette.icon, opacity: pressed || submitting ? 0.5 : 1 },
                ]}>
                <ThemedText style={{ color: palette.text }}>Annuler</ThemedText>
              </Pressable>
              <Pressable
                onPress={handleSubmit}
                disabled={submitting}
                style={({ pressed }) => [
                  styles.actionBtn,
                  styles.submitBtn,
                  { opacity: pressed || submitting ? 0.5 : 1 },
                ]}
                accessibilityRole="button"
                accessibilityLabel="Valider le nouveau résultat">
                <ThemedText style={styles.submitBtnLabel}>
                  {submitting ? 'Envoi...' : 'Valider'}
                </ThemedText>
              </Pressable>
            </View>
          </ScrollView>
        </ThemedView>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 16,
  },
  modal: {
    width: '100%',
    maxWidth: 480,
    maxHeight: '85%',
    borderRadius: 12,
    borderWidth: 1,
  },
  modalContent: {
    padding: 16,
    gap: 16,
  },
  header: {
    gap: 4,
  },
  title: {
    fontSize: 18,
  },
  signalRef: {
    fontSize: 12,
    opacity: 0.7,
  },
  section: {
    gap: 8,
  },
  sectionLabel: {
    fontSize: 12,
    opacity: 0.7,
    textTransform: 'uppercase',
    letterSpacing: 0.3,
  },
  outcomeRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  outcomeBtn: {
    borderWidth: 1,
    borderRadius: 16,
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  outcomeBtnLabel: {
    fontSize: 13,
    fontWeight: '500',
  },
  noteInput: {
    borderWidth: 1,
    borderRadius: 8,
    padding: 10,
    minHeight: 64,
    textAlignVertical: 'top',
    fontSize: 13,
  },
  statusLine: {
    fontSize: 12,
    textAlign: 'center',
  },
  actions: {
    flexDirection: 'row',
    gap: 8,
    justifyContent: 'flex-end',
    marginTop: 4,
  },
  actionBtn: {
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 16,
    minWidth: 100,
    alignItems: 'center',
  },
  cancelBtn: {
    borderWidth: 1,
    backgroundColor: 'transparent',
  },
  submitBtn: {
    backgroundColor: '#2c7be5',
  },
  submitBtnLabel: {
    color: '#ffffff',
    fontWeight: '600',
  },
});
