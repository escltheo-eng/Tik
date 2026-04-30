import { Platform, StyleSheet } from 'react-native';

import ParallaxScrollView from '@/components/parallax-scroll-view';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Fonts } from '@/constants/theme';

export default function HomeScreen() {
  return (
    <ParallaxScrollView
      headerBackgroundColor={{ light: '#0a7ea4', dark: '#0d2a3d' }}
      headerImage={
        <ThemedText
          style={[styles.headerLogo, { fontFamily: Fonts.rounded }]}>
          Tik
        </ThemedText>
      }>
      <ThemedView style={styles.titleContainer}>
        <ThemedText type="title">Dashboard</ThemedText>
      </ThemedView>

      <ThemedText>
        Visualisation temps réel des signaux OSINT produits par le core Tik.
      </ThemedText>

      <ThemedView style={styles.section}>
        <ThemedText type="subtitle">Statut de la connexion</ThemedText>
        <ThemedText>
          Core API : non configuré (à venir en Session 2){'\n'}
          WebSocket signaux : non connecté (à venir en Session 3)
        </ThemedText>
      </ThemedView>

      <ThemedView style={styles.section}>
        <ThemedText type="subtitle">Roadmap Paquet 3</ThemedText>
        <ThemedText>
          • Session 1 : Bootstrap & Hello World (en cours){'\n'}
          • Session 2 : Auth + client HTTP vers le core{'\n'}
          • Session 3 : WebSocket live + Signals Feed{'\n'}
          • Session 4 : KPIs Home + Charts{'\n'}
          • Session 5 : Notifications push + polish
        </ThemedText>
      </ThemedView>

      <ThemedView style={styles.versionBox}>
        <ThemedText style={styles.versionText}>
          tik-dashboard v0.1.0 — Expo SDK 54 — plateforme {Platform.OS}
        </ThemedText>
      </ThemedView>
    </ParallaxScrollView>
  );
}

const styles = StyleSheet.create({
  headerLogo: {
    color: '#ffffff',
    fontSize: 96,
    fontWeight: 'bold',
    bottom: 16,
    left: 24,
    position: 'absolute',
  },
  titleContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  section: {
    gap: 8,
    marginTop: 16,
  },
  versionBox: {
    marginTop: 24,
    paddingTop: 12,
  },
  versionText: {
    fontSize: 12,
    opacity: 0.5,
  },
});
