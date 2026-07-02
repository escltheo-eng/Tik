import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { CosmicCollapsible } from '@/components/cosmic/cosmic-collapsible';
import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';

export default function AboutScreen() {
  const insets = useSafeAreaInsets();
  return (
    <CosmicBackground>
      <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + 8 }]}>
        <Text style={styles.title}>À propos</Text>

        <Text style={styles.intro}>
          Tik est une plateforme OSINT modulaire qui agrège des données multi-sources, score leur
          crédibilité et produit des signaux pondérés sur 3 horizons en parallèle (flash, swing,
          macro).
        </Text>

        <View style={styles.card}>
          <CosmicCollapsible title="Que fait ce dashboard ?">
            <Text style={styles.body}>
              Cette application est en LECTURE SEULE. Elle se connecte au core Tik via HTTP REST et
              WebSocket pour visualiser les signaux en temps réel. Elle ne passe jamais d&apos;ordre
              ni n&apos;altère les bots Zeta/Totem (cf. ADR-003).
            </Text>
          </CosmicCollapsible>

          <CosmicCollapsible title="Architecture en 3 couches">
            <Text style={styles.body}>
              • Couche 1 — Core engine (FastAPI) : source de vérité unique{'\n'}• Couche 2 — SDK
              Python (tik-sdk) : utilisé par les bots backend Zeta/Totem{'\n'}• Couche 3 — Dashboard
              Expo : ce que vous regardez (web et mobile)
            </Text>
          </CosmicCollapsible>

          <CosmicCollapsible title="Garde-fous opérationnels">
            <Text style={styles.body}>
              • Mode SHADOW obligatoire (3 mois minimum) avant connexion réelle Tik ↔ Zeta{'\n'}•
              Budget de test limité à 5 % du capital pendant 1 mois après le mode shadow{'\n'}•
              Aucun bypass du guard V01-V15 côté Zeta — ADR-003
            </Text>
          </CosmicCollapsible>

          <CosmicCollapsible title="Paranoïa contrôlée">
            <Text style={styles.body}>
              Chaque signal Tik livre systématiquement : une hypothèse principale, au moins 2
              contre-scénarios avec leur probabilité estimée, des preuves (evidence) avec leur source
              et leur score de crédibilité, et des triggers techniques pondérés.
            </Text>
          </CosmicCollapsible>
        </View>
      </ScrollView>
    </CosmicBackground>
  );
}

const styles = StyleSheet.create({
  scroll: {
    paddingHorizontal: 16,
    paddingBottom: 32,
    gap: 12,
  },
  title: {
    ...TitleShadow.glow,
    fontFamily: serifTitleFamily,
    color: Cosmic.text,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  intro: {
    color: Cosmic.textDim,
    fontSize: 14,
    lineHeight: 21,
  },
  card: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  body: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 20,
  },
});
