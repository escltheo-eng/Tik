import { useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { AntiFakeNewsBadge } from '@/components/dashboard/anti-fake-news-badge';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { getSignal } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { Signal } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';
import { isLlmCandidateValid } from '@/src/utils/llm';
import { formatLocal } from '@/src/utils/time';

function directionColor(direction: string): string {
  switch (direction) {
    case 'long':
      return '#27ae60';
    case 'short':
      return '#c0392b';
    default:
      return '#7f8c8d';
  }
}

export default function SignalDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { client } = useAuth();
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];

  const [signal, setSignal] = useState<Signal | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSignal = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getSignal(client, id);
      setSignal(data);
    } catch (err) {
      const msg = err instanceof TikError ? err.message : (err as Error).message;
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [client, id]);

  useEffect(() => {
    void fetchSignal();
  }, [fetchSignal]);

  if (loading) {
    return (
      <ThemedView style={styles.center}>
        <ActivityIndicator size="large" />
      </ThemedView>
    );
  }

  if (error || !signal) {
    return (
      <ThemedView style={styles.center}>
        <ThemedText type="subtitle">Erreur</ThemedText>
        <ThemedText style={styles.errorText}>
          {error ?? 'Signal introuvable.'}
        </ThemedText>
        <Pressable
          onPress={() => void fetchSignal()}
          style={({ pressed }) => [
            styles.retry,
            { backgroundColor: Colors.light.tint, opacity: pressed ? 0.7 : 1 },
          ]}>
          <ThemedText style={styles.retryLabel}>Réessayer</ThemedText>
        </Pressable>
      </ThemedView>
    );
  }

  const cardStyle = [
    styles.card,
    { borderColor: palette.icon },
  ];

  return (
    <ScrollView contentContainerStyle={styles.scroll}>
      <ThemedView style={[cardStyle, styles.heroCard]}>
        <ThemedView style={[styles.heroHeader, { backgroundColor: 'transparent' }]}>
          <ThemedText type="title">{signal.entity_id}</ThemedText>
          <View
            style={[styles.directionBadge, { backgroundColor: directionColor(signal.direction) }]}>
            <ThemedText style={styles.directionLabel}>{signal.direction.toUpperCase()}</ThemedText>
          </View>
        </ThemedView>

        <ThemedText style={styles.heroSubtitle}>
          horizon {signal.horizon} • {signal.sources_count} sources
        </ThemedText>

        <ThemedView style={[styles.metricsRow, { backgroundColor: 'transparent' }]}>
          <ThemedView style={[styles.metricBox, { backgroundColor: 'transparent' }]}>
            <ThemedText style={styles.metricLabel}>Confidence</ThemedText>
            <ThemedText type="title" style={styles.metricValue}>
              {(signal.confidence * 100).toFixed(0)}%
            </ThemedText>
          </ThemedView>
          <ThemedView style={[styles.metricBox, { backgroundColor: 'transparent' }]}>
            <ThemedText style={styles.metricLabel}>Veracity</ThemedText>
            <ThemedText type="title" style={styles.metricValue}>
              {(signal.veracity * 100).toFixed(0)}%
            </ThemedText>
          </ThemedView>
        </ThemedView>

        <ThemedText style={styles.metaLine}>
          Émis le {formatLocal(signal.timestamp)}
        </ThemedText>
        {signal.expiry ? (
          <ThemedText style={styles.metaLine}>
            Expire le {formatLocal(signal.expiry)}
          </ThemedText>
        ) : null}
        <AntiFakeNewsBadge status={signal.circuit_breaker_status} />
      </ThemedView>

      {signal.hypothesis ? (
        <ThemedView style={cardStyle}>
          <ThemedText type="subtitle">Hypothèse</ThemedText>
          <ThemedText>{signal.hypothesis}</ThemedText>
        </ThemedView>
      ) : null}

      {/*
        Carte secondaire ADR-012 — affichée conditionnellement :
        - Mode shadow : Signal.advisory.llm_hypothesis_candidate présent
          ET de longueur ≥ 30 mots (filet anti-fantôme en cas de
          stockage par erreur d'un texte template court côté backend).
        - Mode active : Signal.advisory.template_hypothesis présent
          → on montre l'ancien texte template "pour référence" en audit
          permanent post-bascule.
        Si aucun des deux n'est présent (mode disabled ou Paquet 6 pas
        encore livré sur ce signal historique), la carte ne s'affiche pas.
      */}
      {isLlmCandidateValid(signal.advisory.llm_hypothesis_candidate) ? (
        <ThemedView style={[cardStyle, styles.llmCard]}>
          <ThemedView style={[styles.llmHeader, { backgroundColor: 'transparent' }]}>
            <ThemedText type="subtitle">Hypothèse contextuelle</ThemedText>
            <ThemedView style={[styles.llmBadge, { backgroundColor: '#7f8c8d' }]}>
              <ThemedText style={styles.llmBadgeLabel}>LLM · validation</ThemedText>
            </ThemedView>
          </ThemedView>
          <ThemedText>{signal.advisory.llm_hypothesis_candidate}</ThemedText>
        </ThemedView>
      ) : signal.advisory.template_hypothesis ? (
        <ThemedView style={[cardStyle, styles.llmCard]}>
          <ThemedView style={[styles.llmHeader, { backgroundColor: 'transparent' }]}>
            <ThemedText type="subtitle">Hypothèse template</ThemedText>
            <ThemedView style={[styles.llmBadge, { backgroundColor: '#7f8c8d' }]}>
              <ThemedText style={styles.llmBadgeLabel}>référence</ThemedText>
            </ThemedView>
          </ThemedView>
          <ThemedText>{signal.advisory.template_hypothesis}</ThemedText>
        </ThemedView>
      ) : null}

      <ThemedView style={cardStyle}>
        <ThemedText type="subtitle">
          Contre-scénarios ({signal.counter_scenarios.length})
        </ThemedText>
        {signal.counter_scenarios.length === 0 ? (
          <ThemedText style={{ opacity: 0.6 }}>Aucun contre-scénario fourni.</ThemedText>
        ) : (
          signal.counter_scenarios.map((cs, i) => (
            <ThemedView key={`${cs.name}-${i}`} style={[styles.subItem, { borderColor: palette.icon }]}>
              <ThemedText type="defaultSemiBold">{cs.name}</ThemedText>
              <ThemedText style={styles.subMeta}>
                probabilité {(cs.probability * 100).toFixed(0)}%
              </ThemedText>
              <ThemedText>{cs.mitigation}</ThemedText>
            </ThemedView>
          ))
        )}
      </ThemedView>

      <ThemedView style={cardStyle}>
        <ThemedText type="subtitle">Evidence ({signal.evidence.length})</ThemedText>
        {signal.evidence.length === 0 ? (
          <ThemedText style={{ opacity: 0.6 }}>Aucune evidence rattachée.</ThemedText>
        ) : (
          signal.evidence.map((ev, i) => (
            <ThemedView key={`${ev.source}-${i}`} style={[styles.subItem, { borderColor: palette.icon }]}>
              <ThemedView style={[styles.evHeader, { backgroundColor: 'transparent' }]}>
                <ThemedText type="defaultSemiBold">{ev.source}</ThemedText>
                <ThemedText style={styles.subMeta}>
                  score {(ev.score * 100).toFixed(0)}%
                </ThemedText>
              </ThemedView>
              <ThemedText>{ev.fact}</ThemedText>
            </ThemedView>
          ))
        )}
      </ThemedView>

      <ThemedView style={cardStyle}>
        <ThemedText type="subtitle">Triggers ({signal.triggers.length})</ThemedText>
        {signal.triggers.length === 0 ? (
          <ThemedText style={{ opacity: 0.6 }}>Aucun trigger.</ThemedText>
        ) : (
          signal.triggers.map((tg, i) => (
            <ThemedView key={`${tg.type}-${i}`} style={[styles.subItem, { borderColor: palette.icon }]}>
              <ThemedView style={[styles.evHeader, { backgroundColor: 'transparent' }]}>
                <ThemedText type="defaultSemiBold">{tg.type}</ThemedText>
                <ThemedText style={styles.subMeta}>
                  poids {(tg.weight * 100).toFixed(0)}%
                </ThemedText>
              </ThemedView>
              <ThemedText>{tg.value}</ThemedText>
            </ThemedView>
          ))
        )}
      </ThemedView>

      {signal.advisory.notes || signal.advisory.macro_crash_warning || signal.advisory.bias_on_existing_positions ? (
        <ThemedView style={cardStyle}>
          <ThemedText type="subtitle">Advisory</ThemedText>
          {signal.advisory.macro_crash_warning ? (
            <ThemedView style={[styles.cbWarn, { backgroundColor: 'rgba(192, 57, 43, 0.12)' }]}>
              <ThemedText style={{ color: '#c0392b', fontWeight: '600' }}>
                Macro crash warning actif
              </ThemedText>
            </ThemedView>
          ) : null}
          {signal.advisory.bias_on_existing_positions ? (
            <ThemedText>
              Biais sur positions ouvertes : {signal.advisory.bias_on_existing_positions}
            </ThemedText>
          ) : null}
          {signal.advisory.notes ? <ThemedText>{signal.advisory.notes}</ThemedText> : null}
        </ThemedView>
      ) : null}

      <ThemedView style={[cardStyle, styles.idCard]}>
        <ThemedText style={{ fontSize: 11, opacity: 0.5 }}>{signal.id}</ThemedText>
      </ThemedView>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: {
    padding: 16,
    gap: 12,
    paddingBottom: 32,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 12,
  },
  errorText: {
    color: '#c0392b',
    textAlign: 'center',
  },
  retry: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 8,
  },
  retryLabel: {
    color: '#ffffff',
    fontWeight: '600',
  },
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  heroCard: {
    gap: 12,
  },
  heroHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  directionBadge: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
  },
  directionLabel: {
    color: '#ffffff',
    fontWeight: '700',
    fontSize: 12,
    letterSpacing: 0.5,
  },
  heroSubtitle: {
    fontSize: 13,
    opacity: 0.7,
    textTransform: 'lowercase',
  },
  metricsRow: {
    flexDirection: 'row',
    gap: 16,
    marginTop: 4,
  },
  metricBox: {
    flex: 1,
  },
  metricLabel: {
    fontSize: 12,
    opacity: 0.6,
  },
  metricValue: {
    fontSize: 28,
    lineHeight: 32,
  },
  metaLine: {
    fontSize: 12,
    opacity: 0.6,
  },
  cbWarn: {
    padding: 8,
    borderRadius: 6,
    marginTop: 4,
  },
  subItem: {
    borderWidth: 1,
    borderRadius: 8,
    padding: 10,
    gap: 4,
    marginTop: 4,
  },
  subMeta: {
    fontSize: 12,
    opacity: 0.6,
  },
  evHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  idCard: {
    paddingVertical: 8,
    alignItems: 'center',
  },
  llmCard: {
    // Léger fond gris-bleu pour distinguer visuellement la carte
    // secondaire de validation. Border identique aux autres cartes.
    backgroundColor: 'rgba(127, 140, 141, 0.06)',
  },
  llmHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  llmBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
  },
  llmBadgeLabel: {
    color: '#ffffff',
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 0.4,
  },
});
