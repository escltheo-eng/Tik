import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';

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
  return status === 'shadow' ? Cosmic.accent : Cosmic.textFaint;
}

export default function BotsScreen() {
  const insets = useSafeAreaInsets();

  return (
    <CosmicBackground>
      <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + 8 }]}>
        <View style={styles.header}>
          <Text style={styles.title}>Bots</Text>
          <Text style={styles.subtitle}>
            Statut des bots clients Tik. Pour rappel : Tik est en LECTURE pour les bots, jamais en
            EXÉCUTION (ADR-003).
          </Text>
        </View>

        <View style={styles.warningBox}>
          <Text style={styles.warningTitle}>Garde-fou 1 — Mode SHADOW obligatoire</Text>
          <Text style={styles.warningText}>
            Avant toute connexion réelle entre Tik et Zeta, on observe 3 mois minimum. Tik produit
            des signaux qui sont LOGGÉS uniquement, jamais consommés par Zeta. Cet écran ne fait que
            refléter cette posture.
          </Text>
        </View>

        {BOTS.map((bot) => (
          <View key={bot.name} style={styles.card}>
            <View style={styles.cardHeader}>
              <Text style={styles.cardTitle}>{bot.name}</Text>
              <View style={[styles.dot, { backgroundColor: statusColor(bot.status) }]} />
            </View>
            <Text style={[styles.statusBadge, { color: statusColor(bot.status) }]}>
              {bot.statusLabel}
            </Text>
            <Text style={styles.description}>{bot.description}</Text>
            <View style={styles.details}>
              {bot.details.map((d, i) => (
                <Text key={`${bot.name}-${i}`} style={styles.detailItem}>
                  • {d}
                </Text>
              ))}
            </View>
          </View>
        ))}

        <View style={styles.card}>
          <Text style={styles.cardSubtitle}>Pourquoi cet écran ?</Text>
          <Text style={styles.description}>
            Quand Tik passera en mode actif (après les 3 mois shadow), cet écran montrera l’état
            temps réel de chaque bot connecté : nombre de signaux consommés, dernier feedback, PnL
            agrégé, latence, etc. Pour l’instant, c’est un placeholder qui rappelle où on en est dans
            la roadmap.
          </Text>
        </View>
      </ScrollView>
    </CosmicBackground>
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
  title: {
    ...TitleShadow.glow,
    fontFamily: serifTitleFamily,
    color: Cosmic.text,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  subtitle: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 18,
  },
  warningBox: {
    borderWidth: 1,
    borderColor: Cosmic.accent,
    borderRadius: 12,
    padding: 12,
    gap: 6,
    backgroundColor: 'rgba(255,193,94,0.07)',
  },
  warningTitle: {
    color: Cosmic.accent,
    fontSize: 14,
    fontWeight: '700',
  },
  warningText: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 18,
  },
  card: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
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
    ...TitleShadow.soft,
    fontFamily: serifTitleFamily,
    color: Cosmic.text,
    fontSize: 24,
    fontWeight: '700',
  },
  cardSubtitle: {
    color: Cosmic.text,
    fontSize: 15,
    fontWeight: '700',
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
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 19,
  },
  details: {
    gap: 4,
    marginTop: 4,
  },
  detailItem: {
    color: Cosmic.textFaint,
    fontSize: 12,
    lineHeight: 18,
  },
});
