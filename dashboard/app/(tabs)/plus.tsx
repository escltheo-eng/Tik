/**
 * Écran « Plus » / Profil cosmique (refonte γ, bout 6 — maquette enrichi 06).
 *
 * Hub regroupant : performance (hero hit-rate réel + grille + tranches veracity),
 * moteur LLM, santé système, et les accès secondaires (Watchlist, Calendar,
 * Alerts, Config, Bots placeholder). Réutilise les cartes stats existantes
 * (HitRateCard, HitRateByVeracityCard, StatsLLMCard, SourceHealthCard) — données
 * 100 % réelles, zéro backend touché.
 *
 * Honnêteté (Axe #1) : le hit-rate est une MESURE observée, pas une garantie
 * d'edge — go/no-go 2026-05-27 = NO-GO directionnel. Affiché tel quel, sans
 * trend fabriqué.
 *
 * Route dédiée `/plus` (atteinte depuis le Cockpit en attendant la nav 6→5, où
 * Watchlist/Alerts/Config/Calendar deviendront des sous-écrans d'ici).
 */

import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { HitRateByVeracityCard } from '@/components/dashboard/hit-rate-by-veracity-card';
import { HitRateCard } from '@/components/dashboard/hit-rate-card';
import { StatsLLMCard } from '@/components/dashboard/stats-llm-card';
import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import { useAlerts } from '@/src/alerts/AlertsContext';
import { useDashboardKpis } from '@/src/hooks/useDashboardKpis';
import { useHitRate } from '@/src/hooks/useHitRate';
import { useHitRateByVeracity } from '@/src/hooks/useHitRateByVeracity';

function hitColor(rate: number | null | undefined): string {
  if (rate == null) return Cosmic.textFaint;
  if (rate >= 0.6) return Cosmic.long;
  if (rate >= 0.45) return Cosmic.neutral;
  return Cosmic.short;
}

export default function PlusScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const kpis = useDashboardKpis();
  const { unreadCount } = useAlerts();

  // Hero : hit-rate BTC swing 5j (l'horizon le plus exploitable). Mesure réelle.
  const heroHit = useHitRate('BTC', 'swing');
  const goldHit = useHitRate('GOLD', 'swing');

  // Cartes détaillées avec sélecteurs (reprises de l'ex-onglet Calibration).
  const [hrEntity, setHrEntity] = useState<string>('BTC');
  const [hrHorizon, setHrHorizon] = useState<string>('swing');
  const [hrFlagged, setHrFlagged] = useState<boolean>(false);
  const hitRateState = useHitRate(hrEntity, hrHorizon, { includeFlagged: hrFlagged });
  const byVeracityState = useHitRateByVeracity(hrEntity, hrHorizon, { includeFlagged: hrFlagged });

  const hr = heroHit.data?.hit_rate ?? null;
  const heroN = heroHit.data?.n_evaluated ?? 0;
  const heroGain = heroHit.data?.avg_gain_pct ?? null;

  const tile = (label: string, value: string, color?: string, detail?: string) => (
    <View style={styles.tile}>
      <Text style={styles.tileLabel}>{label}</Text>
      <Text style={[styles.tileValue, color ? { color } : null]}>{value}</Text>
      {detail ? <Text style={styles.tileDetail}>{detail}</Text> : null}
    </View>
  );

  const hubRow = (
    icon: string,
    label: string,
    onPress: (() => void) | null,
    note?: string,
    badge?: number,
  ) => (
    <Pressable
      onPress={onPress ?? undefined}
      disabled={!onPress}
      style={({ pressed }) => [styles.hubRow, { opacity: pressed && onPress ? 0.7 : 1 }]}>
      <Text style={styles.hubIcon}>{icon}</Text>
      <Text style={styles.hubLabel}>{label}</Text>
      {badge && badge > 0 ? (
        <View style={styles.hubBadge}>
          <Text style={styles.hubBadgeText}>{badge}</Text>
        </View>
      ) : null}
      {note ? <Text style={styles.hubNote}>{note}</Text> : null}
      <Text style={styles.hubChevron}>{onPress ? '›' : ''}</Text>
    </Pressable>
  );

  return (
    <CosmicBackground>
      <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + 10 }]}>
        {/* En-tête profil */}
        <View style={styles.profilHeader}>
          <View style={styles.avatar}>
            <Text style={styles.avatarLetter}>LT</Text>
          </View>
          <Text style={styles.profilName}>Lola &amp; Théo</Text>
          <Text style={styles.profilId}>tik-server-1 · Helsinki</Text>
        </View>

        {/* Performance — hero */}
        <Text style={styles.section}>Performance Tik</Text>
        <View style={styles.heroBanner}>
          <Text style={styles.heroLabel}>Hit rate mesuré · BTC swing 5j</Text>
          <Text style={[styles.heroValue, { color: hitColor(hr) }]}>
            {hr != null ? `${(hr * 100).toFixed(0)}%` : '—'}
          </Text>
          <Text style={styles.heroSub}>
            {hr != null
              ? `${heroN} signaux mesurés${heroGain != null ? ` · gain moy. ${heroGain >= 0 ? '+' : ''}${heroGain.toFixed(2)}%` : ''}`
              : 'Pas encore assez de signaux mesurés'}
          </Text>
          <Text style={styles.heroCaveat}>
            {"Mesure observée, PAS une garantie d'edge (go/no-go 2026-05-27 = NO-GO directionnel)."}
          </Text>
        </View>

        {/* Grille perf */}
        <View style={styles.grid}>
          {tile(
            'Hit rate BTC swing',
            heroHit.data ? `${(heroHit.data.hit_rate * 100).toFixed(0)}%` : '—',
            hitColor(heroHit.data?.hit_rate),
            heroHit.data ? `${heroHit.data.n_evaluated} mesurés` : undefined,
          )}
          {tile(
            'Hit rate GOLD swing',
            goldHit.data ? `${(goldHit.data.hit_rate * 100).toFixed(0)}%` : '—',
            hitColor(goldHit.data?.hit_rate),
            goldHit.data ? `${goldHit.data.n_evaluated} mesurés` : undefined,
          )}
          {tile('Signaux 24 h', kpis.signalsByHorizon.total.toString(), Cosmic.text, 'tous horizons')}
          {tile(
            'Hypothèses LLM 24 h',
            kpis.llmStatsToday.total.toString(),
            Cosmic.text,
            kpis.llmStatsToday.percentOk != null
              ? `${kpis.llmStatsToday.percentOk.toFixed(0)}% OK`
              : undefined,
          )}
        </View>

        {/* Détail (sélecteurs entité/horizon) — réutilise les cartes existantes */}
        <Text style={styles.section}>Détail hit rate</Text>
        <HitRateCard
          data={hitRateState.data}
          entityId={hrEntity}
          horizon={hrHorizon}
          includeFlagged={hrFlagged}
          onEntityChange={setHrEntity}
          onHorizonChange={setHrHorizon}
          onIncludeFlaggedChange={setHrFlagged}
          loading={hitRateState.loading}
          error={hitRateState.error}
        />
        <HitRateByVeracityCard
          data={byVeracityState.data}
          entityId={hrEntity}
          horizon={hrHorizon}
          loading={byVeracityState.loading}
          error={byVeracityState.error}
        />

        {/* Moteur LLM */}
        <Text style={styles.section}>Moteur LLM (Ollama)</Text>
        <StatsLLMCard stats={kpis.llmStatsToday} loading={kpis.loading} error={kpis.signals24hError} />

        {/* Hub d'accès (santé des sources = onglet Sources, pas dupliquée ici) */}
        <Text style={styles.section}>Accès</Text>
        <View style={styles.hub}>
          {hubRow('★', 'Watchlist', () => router.push('/watchlist'))}
          {hubRow('📅', 'Calendrier macro', () => router.push('/macro'))}
          {hubRow('🔔', 'Alertes', () => router.push('/alerts'), undefined, unreadCount)}
          {hubRow('⚙', 'Configuration', () => router.push('/config'))}
          {hubRow('ℹ', 'À propos', () => router.push('/about'))}
          {hubRow('🤖', 'Bots', null, 'bientôt')}
        </View>
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
  profilHeader: {
    alignItems: 'center',
    gap: 4,
    paddingBottom: 6,
  },
  avatar: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: Cosmic.accent,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 6,
  },
  avatarLetter: {
    color: Cosmic.bgDeep,
    fontSize: 26,
    fontWeight: '800',
    fontFamily: serifTitleFamily,
  },
  profilName: {
    ...TitleShadow.glow,
    fontFamily: serifTitleFamily,
    color: Cosmic.text,
    fontSize: 20,
    fontStyle: 'italic',
    fontWeight: '700',
  },
  profilId: {
    color: Cosmic.textFaint,
    fontSize: 10,
    letterSpacing: 1,
    fontFamily: Fonts.mono,
  },
  section: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginTop: 8,
  },
  heroBanner: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 16,
    padding: 18,
    alignItems: 'center',
    gap: 4,
  },
  heroLabel: {
    color: Cosmic.textFaint,
    fontSize: 10,
    letterSpacing: 1,
    textTransform: 'uppercase',
    fontFamily: Fonts.mono,
  },
  heroValue: {
    fontFamily: serifTitleFamily,
    fontStyle: 'italic',
    fontSize: 44,
    fontWeight: '700',
  },
  heroSub: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontFamily: Fonts.mono,
  },
  heroCaveat: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontStyle: 'italic',
    textAlign: 'center',
    marginTop: 4,
    lineHeight: 16,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  tile: {
    flexBasis: '47%',
    flexGrow: 1,
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 3,
  },
  tileLabel: {
    color: Cosmic.textFaint,
    fontSize: 10,
    letterSpacing: 0.4,
    textTransform: 'uppercase',
    fontFamily: Fonts.mono,
  },
  tileValue: {
    color: Cosmic.text,
    fontSize: 20,
    fontWeight: '700',
    fontFamily: Fonts.mono,
  },
  tileDetail: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontFamily: Fonts.mono,
  },
  hub: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 14,
    overflow: 'hidden',
  },
  hubRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 14,
    paddingHorizontal: 14,
    borderBottomWidth: 1,
    borderBottomColor: Cosmic.border,
  },
  hubIcon: {
    fontSize: 16,
    width: 22,
    textAlign: 'center',
  },
  hubLabel: {
    flex: 1,
    color: Cosmic.text,
    fontSize: 15,
    fontWeight: '600',
  },
  hubNote: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontFamily: Fonts.mono,
  },
  hubBadge: {
    minWidth: 20,
    height: 20,
    borderRadius: 10,
    paddingHorizontal: 6,
    backgroundColor: Cosmic.short,
    alignItems: 'center',
    justifyContent: 'center',
  },
  hubBadgeText: {
    color: '#ffffff',
    fontSize: 11,
    fontWeight: '800',
  },
  hubChevron: {
    color: Cosmic.textDim,
    fontSize: 18,
    width: 14,
    textAlign: 'right',
  },
});
