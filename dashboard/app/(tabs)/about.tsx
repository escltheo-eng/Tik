import { StyleSheet } from 'react-native';

import { Collapsible } from '@/components/ui/collapsible';
import ParallaxScrollView from '@/components/parallax-scroll-view';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Fonts } from '@/constants/theme';

export default function AboutScreen() {
  return (
    <ParallaxScrollView
      headerBackgroundColor={{ light: '#D0D0D0', dark: '#353636' }}
      headerImage={
        <ThemedText
          style={[styles.headerLogo, { fontFamily: Fonts.rounded }]}>
          ?
        </ThemedText>
      }>
      <ThemedView style={styles.titleContainer}>
        <ThemedText type="title">À propos</ThemedText>
      </ThemedView>

      <ThemedText>
        Tik est une plateforme OSINT modulaire qui agrège des données multi-sources,
        score leur crédibilité et produit des signaux pondérés sur 3 horizons en parallèle
        (flash, swing, macro).
      </ThemedText>

      <Collapsible title="Que fait ce dashboard ?">
        <ThemedText>
          Cette application est en LECTURE SEULE. Elle se connecte au core Tik via HTTP REST
          et WebSocket pour visualiser les signaux en temps réel. Elle ne passe jamais d&apos;ordre
          ni n&apos;altère les bots Zeta/Totem (cf. ADR-003).
        </ThemedText>
      </Collapsible>

      <Collapsible title="Architecture en 3 couches">
        <ThemedText>
          • Couche 1 — Core engine (FastAPI) : source de vérité unique{'\n'}
          • Couche 2 — SDK Python (tik-sdk) : utilisé par les bots backend Zeta/Totem{'\n'}
          • Couche 3 — Dashboard Expo : ce que vous regardez (web et mobile)
        </ThemedText>
      </Collapsible>

      <Collapsible title="Garde-fous opérationnels">
        <ThemedText>
          • Mode SHADOW obligatoire (3 mois minimum) avant connexion réelle Tik ↔ Zeta{'\n'}
          • Budget de test limité à 5 % du capital pendant 1 mois après le mode shadow{'\n'}
          • Aucun bypass du guard V01-V15 côté Zeta — ADR-003
        </ThemedText>
      </Collapsible>

      <Collapsible title="Paranoïa contrôlée">
        <ThemedText>
          Chaque signal Tik livre systématiquement : une hypothèse principale, au moins
          2 contre-scénarios avec leur probabilité estimée, des preuves (evidence) avec
          leur source et leur score de crédibilité, et des triggers techniques pondérés.
        </ThemedText>
      </Collapsible>
    </ParallaxScrollView>
  );
}

const styles = StyleSheet.create({
  headerLogo: {
    color: '#808080',
    fontSize: 200,
    fontWeight: 'bold',
    bottom: -40,
    left: 24,
    position: 'absolute',
  },
  titleContainer: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 8,
  },
});
