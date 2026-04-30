import { ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';

interface BotInfo {
  name: string;
  description: string;
  status: 'shadow' | 'planned';
  statusLabel: string;
  details: string[];
}

const BOTS: BotInfo[] = [
  {
    name: 'Zeta',
    description: 'Bot trading déterministe Python FastAPI sur MT5 / ActivTrades, leverage 1:1000.',
    status: 'shadow',
    statusLabel: 'Mode SHADOW — non connecté à Tik',
    details: [
      '29 routes API + 22 services',
      'Stratégies actives : H1 Adaptive (BTC + GOLD), Weekend Scalp (BTC seul)',
      'Guard pipeline V01-V15 systématique (ADR-003)',
      'Connexion réelle à Tik après 3 mois minimum d’observation (Garde-fou 1)',
    ],
  },
  {
    name: 'Totem',
    description: 'IA de trading autonome basée sur du machine learning.',
    status: 'planned',
    statusLabel: 'Intégration prévue — détails à venir',
    details: [
      'Architecture séparée du moteur Zeta',
      'Tik enverra des vecteurs de features ML enrichis (cross-validés)',
      'Spécifications complètes à finaliser avec l’équipe Totem',
    ],
  },
];

function statusColor(status: BotInfo['status']): string {
  return status === 'shadow' ? '#f39c12' : '#7f8c8d';
}

export default function BotsScreen() {
  const insets = useSafeAreaInsets();
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];

  return (
    <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + 8 }]}>
      <View style={styles.header}>
        <ThemedText type="title">Bots</ThemedText>
        <ThemedText style={styles.subtitle}>
          Statut des bots clients Tik. Pour rappel : Tik est en LECTURE pour les bots, jamais en
          EXÉCUTION (ADR-003).
        </ThemedText>
      </View>

      <ThemedView style={[styles.warningBox, { borderColor: '#f39c12' }]}>
        <ThemedText type="defaultSemiBold" style={{ color: '#f39c12' }}>
          Garde-fou 1 — Mode SHADOW obligatoire
        </ThemedText>
        <ThemedText style={styles.warningText}>
          Avant toute connexion réelle entre Tik et Zeta, on observe 3 mois minimum. Tik produit
          des signaux qui sont LOGGÉS uniquement, jamais consommés par Zeta. Cet écran ne fait
          que refléter cette posture.
        </ThemedText>
      </ThemedView>

      {BOTS.map((bot) => (
        <ThemedView
          key={bot.name}
          style={[styles.card, { borderColor: palette.icon }]}>
          <View style={styles.cardHeader}>
            <ThemedText type="title" style={styles.cardTitle}>
              {bot.name}
            </ThemedText>
            <View style={[styles.dot, { backgroundColor: statusColor(bot.status) }]} />
          </View>
          <ThemedText style={[styles.statusBadge, { color: statusColor(bot.status) }]}>
            {bot.statusLabel}
          </ThemedText>
          <ThemedText style={styles.description}>{bot.description}</ThemedText>
          <View style={styles.details}>
            {bot.details.map((d, i) => (
              <ThemedText key={`${bot.name}-${i}`} style={styles.detailItem}>
                • {d}
              </ThemedText>
            ))}
          </View>
        </ThemedView>
      ))}

      <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
        <ThemedText type="defaultSemiBold">Pourquoi cet écran ?</ThemedText>
        <ThemedText style={styles.description}>
          Quand Tik passera en mode actif (après les 3 mois shadow), cet écran montrera l’état
          temps réel de chaque bot connecté : nombre de signaux consommés, dernier feedback,
          PnL agrégé, latence, etc. Pour l’instant, c’est un placeholder qui rappelle où on en
          est dans la roadmap.
        </ThemedText>
      </ThemedView>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: {
    paddingHorizontal: 16,
    paddingBottom: 24,
    gap: 12,
  },
  header: {
    gap: 8,
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 13,
    opacity: 0.7,
    lineHeight: 18,
  },
  warningBox: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 6,
    backgroundColor: 'rgba(243, 156, 18, 0.06)',
  },
  warningText: {
    fontSize: 13,
    lineHeight: 18,
    opacity: 0.85,
  },
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  cardTitle: {
    fontSize: 24,
  },
  dot: {
    width: 12,
    height: 12,
    borderRadius: 6,
  },
  statusBadge: {
    fontSize: 13,
    fontWeight: '600',
  },
  description: {
    fontSize: 13,
    opacity: 0.85,
    lineHeight: 18,
  },
  details: {
    gap: 4,
    marginTop: 4,
  },
  detailItem: {
    fontSize: 12,
    opacity: 0.75,
    lineHeight: 18,
  },
});
