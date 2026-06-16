/**
 * Écran « Sources » cosmique (refonte γ, bout 6 — dispatch depuis le Cockpit).
 *
 * Regroupe les sources OSINT qui alimentent les signaux : santé/fraîcheur des
 * sources + marchés prédictifs (Polymarket) + positionnement dérivés + actualité
 * (breaking / top headlines). Réutilise les composants + hooks existants (zéro
 * backend touché) — seul le contenant est cosmique.
 *
 * Route dédiée `/sources` (atteinte depuis le Cockpit en attendant la nav 6→5).
 * Honnêteté (Axe #1) : aucune source n'a d'edge prouvé seule — elles se croisent.
 */

import { useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { CosmicDerivatives } from '@/components/cosmic/cosmic-derivatives';
import { CosmicPolymarket } from '@/components/cosmic/cosmic-polymarket';
import { CosmicSourceHealth } from '@/components/cosmic/cosmic-source-health';
import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import { useDerivatives } from '@/src/hooks/useDerivatives';
import { usePolymarket } from '@/src/hooks/usePolymarket';

export default function SourcesScreen() {
  const insets = useSafeAreaInsets();
  const [polymarketEntity, setPolymarketEntity] = useState<string>('GOLD');
  const polymarketState = usePolymarket(polymarketEntity, { limit: 4 });
  const derivativesState = useDerivatives('BTC');

  return (
    <CosmicBackground>
      <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + 10 }]}>
        <View style={styles.header}>
          <Text style={styles.brand}>
            Tik<Text style={styles.brandSub}> · sources</Text>
          </Text>
          <Text style={styles.brandTag}>Observatoire OSINT</Text>
        </View>

        <Text style={styles.intro}>
          {"Les sources qui alimentent les signaux — état, fraîcheur, contexte. Aucune n'a d'edge " +
            'prouvé seule : elles se croisent (cross-validation).'}
        </Text>

        <CosmicSourceHealth />

        <CosmicPolymarket
          snapshot={polymarketState.snapshot}
          entityId={polymarketEntity}
          onEntityChange={setPolymarketEntity}
          loading={polymarketState.loading}
          error={polymarketState.error}
        />

        <CosmicDerivatives
          snapshot={derivativesState.snapshot}
          loading={derivativesState.loading}
          error={derivativesState.error}
        />

        <Text style={styles.footer}>L&apos;actualité (breaking + top headlines) est sur le Cockpit.</Text>
      </ScrollView>
    </CosmicBackground>
  );
}

const styles = StyleSheet.create({
  scroll: {
    paddingHorizontal: 16,
    paddingBottom: 40,
    gap: 12,
  },
  header: {
    gap: 3,
  },
  brand: {
    ...TitleShadow.glow,
    fontFamily: serifTitleFamily,
    color: Cosmic.accent,
    fontSize: 26,
    fontStyle: 'italic',
    fontWeight: '700',
  },
  brandSub: {
    color: Cosmic.text,
    fontWeight: '400',
  },
  brandTag: {
    color: Cosmic.textFaint,
    fontSize: 9,
    letterSpacing: 1.5,
    textTransform: 'uppercase',
    fontFamily: Fonts.mono,
  },
  intro: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 19,
    marginBottom: 2,
  },
  footer: {
    color: Cosmic.textFaint,
    fontSize: 12,
    fontStyle: 'italic',
    marginTop: 8,
  },
});
