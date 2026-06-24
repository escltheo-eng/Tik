/**
 * Page « Macro » cosmique (refonte γ).
 *
 * Regroupe l'horloge de séances + le CONTEXTE macro objectif : « quand trader »
 * (séances Sydney/Tokyo/Londres/NY + or COMEX), régime macro (Fed Net Liquidity +
 * indicateurs FRED), liquidité mondiale (Fed+ECB+BoJ), anticipations de taux Fed
 * (CME FedWatch). Réutilise les MÊMES hooks data que la Home (`useMacroRegime`,
 * `useRateProbabilities`) — seul l'affichage est cosmique.
 *
 * Refonte nav Stage 1 (2026-06-24) : les 8 cartes, jusque-là empilées en
 * « déversoir », sont regroupées en 4 FAMILLES repliables (`CosmicSection`) —
 * Liquidité / Risque / Anticipations / Cross-asset. Réduit le scroll et clarifie
 * la logique métier. Les blocs sensibles au temps (séances + fenêtre de
 * discipline ±4h) restent TOUJOURS visibles en tête.
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
import { CosmicCrossAssetCard } from '@/components/cosmic/cosmic-cross-asset-card';
import { CosmicDisciplineWindow } from '@/components/cosmic/cosmic-discipline-window';
import { CosmicGlobalLiquidityCard } from '@/components/cosmic/cosmic-global-liquidity-card';
import { CosmicMacroRegimeCard } from '@/components/cosmic/cosmic-macro-regime-card';
import { CosmicRateProbabilitiesCard } from '@/components/cosmic/cosmic-rate-probabilities-card';
import { CosmicRiskRegimeCard } from '@/components/cosmic/cosmic-risk-regime-card';
import { CosmicSection } from '@/components/cosmic/cosmic-section';
import { CosmicSessionClock } from '@/components/cosmic/cosmic-session-clock';
import { CosmicStablecoinsCard } from '@/components/cosmic/cosmic-stablecoins-card';
import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import { useCrossAsset } from '@/src/hooks/useCrossAsset';
import { useMacroRegime } from '@/src/hooks/useMacroRegime';
import { useRateProbabilities } from '@/src/hooks/useRateProbabilities';
import { useStablecoins } from '@/src/hooks/useStablecoins';

export default function MacroCosmicScreen() {
  const router = useRouter();
  const macro = useMacroRegime();
  const rateProb = useRateProbabilities();
  const stablecoins = useStablecoins();
  const crossAsset = useCrossAsset();

  const [refreshing, setRefreshing] = useState(false);
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await Promise.all([
        macro.refresh(),
        rateProb.refresh(),
        stablecoins.refresh(),
        crossAsset.refresh(),
      ]);
    } finally {
      setRefreshing(false);
    }
  }, [macro, rateProb, stablecoins, crossAsset]);

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

        {/* Toujours visibles : sensibles au temps (discipline ±4h). */}
        <CosmicSessionClock />
        <CosmicDisciplineWindow />

        {/* Familles de contexte, repliables (Stage 1 refonte nav). */}
        <CosmicSection
          title="Liquidité"
          subtitle="Quand le capital entre / sort du marché"
          defaultOpen>
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
          <CosmicStablecoinsCard
            stablecoins={stablecoins.stablecoins}
            loading={stablecoins.loading}
            error={stablecoins.error}
          />
        </CosmicSection>

        <CosmicSection title="Risque" subtitle="Le stress de marché (VIX, spreads de crédit)">
          <CosmicRiskRegimeCard
            risk={macro.regime?.risk_regime ?? null}
            loading={macro.loading}
            error={macro.error}
          />
        </CosmicSection>

        <CosmicSection title="Anticipations" subtitle="Où le marché voit les taux de la Fed">
          <CosmicRateProbabilitiesCard
            rates={rateProb.rates}
            loading={rateProb.loading}
            error={rateProb.error}
          />
        </CosmicSection>

        <CosmicSection title="Cross-asset" subtitle="Avec quoi le BTC co-bouge (actions, or, dollar)">
          <CosmicCrossAssetCard
            crossAsset={crossAsset.crossAsset}
            loading={crossAsset.loading}
            error={crossAsset.error}
          />
        </CosmicSection>

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
