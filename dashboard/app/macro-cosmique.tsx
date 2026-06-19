/**
 * Page « Macro » cosmique (refonte γ).
 *
 * Regroupe l'horloge de séances + le CONTEXTE macro objectif : « quand trader »
 * (séances Sydney/Tokyo/Londres/NY + or COMEX), régime macro (Fed Net Liquidity +
 * indicateurs FRED), liquidité mondiale (Fed+ECB+BoJ), anticipations de taux Fed
 * (CME FedWatch). Réutilise les MÊMES hooks data que la Home (`useMacroRegime`,
 * `useRateProbabilities`) — seul l'affichage est cosmique.
 *
 * Route DÉDIÉE `/macro-cosmique`, atteinte depuis le bandeau contexte en haut de
 * la liste Signals + le bandeau du Cockpit (pas un onglet : choix trader de garder
 * 5 onglets propres, l'accès se fait par les bandeaux). L'ancienne page `/macro`
 * (calendrier macro) reste distincte ; un lien en bas y renvoie.
 *
 * CONTEXTE STRICT : rien ici ne touche direction/veracity/combined_bias (NO-GO
 * directionnel inchangé). On affiche des séries datées + des horaires de place,
 * on n'affirme rien sur le sens du prix.
 */

import { useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { CosmicDisciplineWindow } from '@/components/cosmic/cosmic-discipline-window';
import { CosmicGlobalLiquidityCard } from '@/components/cosmic/cosmic-global-liquidity-card';
import { CosmicMacroRegimeCard } from '@/components/cosmic/cosmic-macro-regime-card';
import { CosmicRateProbabilitiesCard } from '@/components/cosmic/cosmic-rate-probabilities-card';
import { CosmicSessionClock } from '@/components/cosmic/cosmic-session-clock';
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
            Quand le marché bouge (séances) et dans quel décor (FRED + futures Fed). Rien ici ne
            touche les signaux Tik : du contexte, pas une prédiction du prix.
          </Text>
        </View>

        <CosmicSessionClock />

        <CosmicDisciplineWindow />

        <CosmicMacroRegimeCard regime={macro.regime} loading={macro.loading} error={macro.error} />

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
