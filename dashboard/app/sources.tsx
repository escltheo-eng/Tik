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
import { BreakingNewsCard } from '@/components/dashboard/breaking-news-card';
import { DerivativesCard } from '@/components/dashboard/derivatives-card';
import { PolymarketCard } from '@/components/dashboard/polymarket-card';
import { SourceHealthCard } from '@/components/dashboard/source-health-card';
import { TopHeadlinesCard } from '@/components/dashboard/top-headlines-card';
import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import { useDerivatives } from '@/src/hooks/useDerivatives';
import { usePolymarket } from '@/src/hooks/usePolymarket';
import { useTopHeadlines } from '@/src/hooks/useTopHeadlines';

export default function SourcesScreen() {
  const insets = useSafeAreaInsets();
  const [headlinesEntity, setHeadlinesEntity] = useState<string>('BTC');
  const headlinesState = useTopHeadlines(headlinesEntity, { limit: 5 });
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

        <Text style={styles.section}>Santé des sources</Text>
        <SourceHealthCard />

        <Text style={styles.section}>Marchés prédictifs</Text>
        <PolymarketCard
          snapshot={polymarketState.snapshot}
          entityId={polymarketEntity}
          onEntityChange={setPolymarketEntity}
          displayLimit={3}
          marketsPerEvent={4}
          loading={polymarketState.loading}
          error={polymarketState.error}
        />

        <Text style={styles.section}>Positionnement dérivés (BTC)</Text>
        <DerivativesCard
          snapshot={derivativesState.snapshot}
          loading={derivativesState.loading}
          error={derivativesState.error}
        />

        <Text style={styles.section}>Actualité</Text>
        <BreakingNewsCard />
        <TopHeadlinesCard
          headlines={headlinesState.headlines}
          entityId={headlinesEntity}
          onEntityChange={setHeadlinesEntity}
          displayLimit={5}
          loading={headlinesState.loading}
          error={headlinesState.error}
        />
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
  section: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginTop: 8,
  },
});
