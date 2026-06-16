/**
 * Page « Macro » cosmique (refonte γ, bout 3).
 *
 * Regroupe le CONTEXTE macro objectif — déménagé hors de la Home pour la
 * désencombrer (cf. problème « signal enterré » corrigé au bout 1) : régime macro
 * (Fed Net Liquidity + indicateurs FRED), liquidité mondiale (Fed+ECB+BoJ),
 * anticipations de taux Fed (CME FedWatch). Réutilise les MÊMES hooks data que la
 * Home (`useMacroRegime`, `useRateProbabilities`) — seul l'affichage est cosmique.
 *
 * Route DÉDIÉE `/macro-cosmique`, atteinte depuis le bandeau contexte en haut de
 * la liste Signals cosmique. L'ancienne page `/macro` (calendrier macro, thème
 * clair) reste intacte ; un lien en bas y renvoie.
 *
 * CONTEXTE STRICT : rien ici ne touche direction/veracity/combined_bias (NO-GO
 * directionnel inchangé). On affiche des séries datées, on n'affirme rien.
 */

import { useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { CosmicGlobalLiquidityCard } from '@/components/cosmic/cosmic-global-liquidity-card';
import { CosmicMacroRegimeCard } from '@/components/cosmic/cosmic-macro-regime-card';
import { CosmicRateProbabilitiesCard } from '@/components/cosmic/cosmic-rate-probabilities-card';
import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import { useMacroRegime } from '@/src/hooks/useMacroRegime';
import { useRateProbabilities } from '@/src/hooks/useRateProbabilities';

export default function MacroCosmicScreen() {
  const router = useRouter();
  const macro = useMacroRegime();
  const rateProb = useRateProbabilities();

  const [refreshing, setRefreshing] = useState(false);
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await Promise.all([macro.refresh(), rateProb.refresh()]);
    } finally {
      setRefreshing(false);
    }
  }, [macro, rateProb]);

  return (
    <CosmicBackground>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Cosmic.accent} />
        }>
        <View style={styles.headerBlock}>
          <Text style={styles.title}>Macro</Text>
          <Text style={styles.subtitle}>
            Contexte objectif (FRED + futures Fed). Ces chiffres ne touchent JAMAIS les signaux
            Tik — ils servent à situer le décor, pas à prédire le prix.
          </Text>
        </View>

        <CosmicMacroRegimeCard
          regime={macro.regime}
          loading={macro.loading}
          error={macro.error}
        />

        <CosmicGlobalLiquidityCard
          globalLiquidity={macro.regime?.global_liquidity ?? null}
          loading={macro.loading}
          error={macro.error}
        />

        <CosmicRateProbabilitiesCard
          rates={rateProb.rates}
          loading={rateProb.loading}
          error={rateProb.error}
        />

        <Pressable
          onPress={() => router.push('/macro')}
          style={({ pressed }) => [styles.calendarLink, { opacity: pressed ? 0.6 : 1 }]}
          accessibilityRole="button"
          accessibilityLabel="Voir le calendrier macro">
          <Text style={styles.calendarLinkText}>📅 Voir le calendrier macro (events à venir) ›</Text>
        </Pressable>
      </ScrollView>
    </CosmicBackground>
  );
}

const styles = StyleSheet.create({
  scroll: {
    padding: 16,
    paddingBottom: 40,
    gap: 12,
  },
  headerBlock: {
    gap: 6,
    marginBottom: 2,
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
  calendarLink: {
    borderWidth: 1,
    borderColor: Cosmic.borderStrong,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 14,
    alignItems: 'center',
    backgroundColor: Cosmic.card,
  },
  calendarLinkText: {
    color: Cosmic.accent,
    fontSize: 14,
    fontWeight: '600',
  },
});
