/**
 * Home → COCKPIT cosmique (refonte γ, bout 6).
 *
 * Sous-onglet Marché transformé en cockpit « Puis-je trader ? » : bandeau macro
 * réel + statut de discipline (F1) + dernier signal BTC (CosmicSignalCard) +
 * trades ouverts + prochain event. Les cartes de contexte (breaking, headlines,
 * Polymarket, dérivés) restent TEMPORAIREMENT en bas en attendant l'onglet
 * Sources (elles y déménageront). Les sous-onglets Calibration/Système gardent
 * leur contenu (sombre via le thème global) en attendant l'onglet Plus.
 *
 * Honnêteté (Axe #1) : le statut de discipline dit « y a-t-il un frein ? », PAS
 * « Tik dit d'acheter » — aucun edge directionnel prouvé (NO-GO 2026-05-27).
 * Données 100 % réelles ; rien d'inventé (pas de Silver, Stress, influence).
 */

import type { ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { CosmicSignalCard } from '@/components/cosmic/cosmic-signal-card';
import { BreakingNewsCard } from '@/components/dashboard/breaking-news-card';
import { DerivativesCard } from '@/components/dashboard/derivatives-card';
import { HitRateByVeracityCard } from '@/components/dashboard/hit-rate-by-veracity-card';
import { HitRateCard } from '@/components/dashboard/hit-rate-card';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { MiniSparkline } from '@/components/dashboard/mini-sparkline';
import { PolymarketCard } from '@/components/dashboard/polymarket-card';
import { SourceHealthCard } from '@/components/dashboard/source-health-card';
import { StatsLLMCard } from '@/components/dashboard/stats-llm-card';
import { TopHeadlinesCard } from '@/components/dashboard/top-headlines-card';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Cosmic, TitleShadow, directionMeta, serifTitleFamily } from '@/constants/cosmic';
import { Colors, Fonts } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { getHealth } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { Health, Signal } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';
import { useDashboardKpis } from '@/src/hooks/useDashboardKpis';
import { useDerivatives } from '@/src/hooks/useDerivatives';
import { useHitRate } from '@/src/hooks/useHitRate';
import { useHitRateByVeracity } from '@/src/hooks/useHitRateByVeracity';
import { useMacroRegime } from '@/src/hooks/useMacroRegime';
import { usePolymarket } from '@/src/hooks/usePolymarket';
import { useTick } from '@/src/hooks/use-tick';
import { useTopHeadlines } from '@/src/hooks/useTopHeadlines';
import { useUpcomingMacroEvents } from '@/src/hooks/useUpcomingMacroEvents';
import { useRouter } from 'expo-router';
import { useTrades } from '@/src/journal/useTrades';
import { formatLocal, parseUtcIso } from '@/src/utils/time';

import pkg from '../../package.json';

const APP_VERSION = pkg.version;
const HEALTH_REFRESH_INTERVAL_MS = 30_000;
const MACRO_WINDOW_MS = 4 * 3600 * 1000; // ±4h discipline (Garde-fou 2-bis)
const SWING_VERACITY_FLOOR = 0.85; // seuil transitoire Garde-fou 2-bis

type HomeTab = 'market' | 'calibration' | 'system';
const TAB_LABELS: Record<HomeTab, string> = {
  market: 'Cockpit',
  calibration: 'Calibration',
  system: 'Système',
};
const TAB_ORDER: HomeTab[] = ['market', 'calibration', 'system'];

interface HealthState {
  status: 'idle' | 'loading' | 'ok' | 'error';
  data: Health | null;
  error: string | null;
  lastChecked: Date | null;
}
const INITIAL_HEALTH: HealthState = { status: 'idle', data: null, error: null, lastChecked: null };

/** Label + couleur d'un régime de liquidité. */
function regimeView(r: string | null | undefined): { label: string; color: string } {
  if (r === 'expansion') return { label: 'Expansion', color: Cosmic.long };
  if (r === 'contraction') return { label: 'Contraction', color: Cosmic.neutral };
  if (r === 'neutral') return { label: 'Stable', color: Cosmic.textDim };
  return { label: '—', color: Cosmic.textFaint };
}

export default function HomeScreen() {
  const { client, baseUrl } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];

  const [activeTab, setActiveTab] = useState<HomeTab>('market');
  const [healthState, setHealthState] = useState<HealthState>(INITIAL_HEALTH);

  const checkHealth = useCallback(async () => {
    setHealthState((s) => ({ ...s, status: 'loading' }));
    try {
      const data = await getHealth(client);
      setHealthState({ status: 'ok', data, error: null, lastChecked: new Date() });
    } catch (err) {
      const msg = err instanceof TikError ? err.message : (err as Error).message;
      setHealthState({ status: 'error', data: null, error: msg, lastChecked: new Date() });
    }
  }, [client]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (!cancelled) await checkHealth();
    })();
    const id = setInterval(() => {
      if (!cancelled) void checkHealth();
    }, HEALTH_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [checkHealth]);

  const kpis = useDashboardKpis();
  const [headlinesEntity, setHeadlinesEntity] = useState<string>('BTC');
  const headlinesState = useTopHeadlines(headlinesEntity, { limit: 5 });
  const [polymarketEntity, setPolymarketEntity] = useState<string>('GOLD');
  const polymarketState = usePolymarket(polymarketEntity, { limit: 4 });
  const derivativesState = useDerivatives('BTC');
  const macroEventsState = useUpcomingMacroEvents({ hours: 7 * 24, limit: 8 });
  const macroRegimeState = useMacroRegime();
  const { trades } = useTrades();
  const [hitRateEntity, setHitRateEntity] = useState<string>('BTC');
  const [hitRateHorizon, setHitRateHorizon] = useState<string>('swing');
  const [hitRateIncludeFlagged, setHitRateIncludeFlagged] = useState<boolean>(false);
  const hitRateState = useHitRate(hitRateEntity, hitRateHorizon, {
    includeFlagged: hitRateIncludeFlagged,
  });
  const hitRateByVeracityState = useHitRateByVeracity(hitRateEntity, hitRateHorizon, {
    includeFlagged: hitRateIncludeFlagged,
  });
  useTick();

  const statusLabel: Record<HealthState['status'], string> = {
    idle: 'Inactif',
    loading: 'Vérification…',
    ok: 'Connecté',
    error: 'Hors ligne',
  };
  const statusColor: Record<HealthState['status'], string> = {
    idle: Cosmic.textFaint,
    loading: Cosmic.textFaint,
    ok: Cosmic.long,
    error: Cosmic.short,
  };

  // --- Données dérivées du cockpit (100 % réelles) ---
  const latestBtc: Signal | null = kpis.lastSignalByEntity['BTC'] ?? null;

  const latestBtcSwing = useMemo(
    () =>
      [...kpis.signals24h]
        .filter((s) => s.entity_id === 'BTC' && s.horizon === 'swing')
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0] ?? null,
    [kpis.signals24h],
  );

  // Event macro HIGH dans la fenêtre ±4h (discipline Garde-fou 2-bis).
  const macroBlockEvent = useMemo(() => {
    const now = Date.now();
    return (
      macroEventsState.events.find(
        (e) =>
          e.importance === 'HIGH' &&
          Math.abs(parseUtcIso(e.scheduled_for).getTime() - now) <= MACRO_WINDOW_MS,
      ) ?? null
    );
  }, [macroEventsState.events]);

  const nextEvent = macroEventsState.events[0] ?? null;
  const openTrades = useMemo(() => trades.filter((t) => t.status === 'open'), [trades]);

  // Statut de discipline (le pire critère donne la couleur). NE dit PAS « achète ».
  const swingVeracityOk = latestBtcSwing ? latestBtcSwing.veracity >= SWING_VERACITY_FLOOR : false;
  const discipline: { color: string; head: string } = macroBlockEvent
    ? { color: Cosmic.short, head: '🔴 Frein de discipline' }
    : !latestBtcSwing || !swingVeracityOk
      ? { color: Cosmic.neutral, head: '🟠 Prudence' }
      : { color: Cosmic.long, head: '🟢 Aucun frein de discipline' };

  const criteria: { ok: boolean; text: string }[] = [
    macroBlockEvent
      ? { ok: false, text: `Event macro HIGH ±4h (${macroBlockEvent.event_name}) — ne pas entrer, ou sizing ÷2` }
      : { ok: true, text: "Pas d'event macro HIGH dans les ±4h" },
    latestBtcSwing
      ? {
          ok: swingVeracityOk,
          text: `Veracity dernier swing BTC ${(latestBtcSwing.veracity * 100).toFixed(0)}%${swingVeracityOk ? '' : ' < 85 %'}`,
        }
      : { ok: false, text: 'Pas de signal swing BTC récent' },
    { ok: true, text: 'Marché BTC ouvert (24/7)' },
    { ok: true, text: 'Sizing 1 % max — ta vraie protection' },
  ];

  // ---------- COCKPIT (sous-onglet Marché) ----------
  const renderMarketTab = () => (
    <>
      {/* Bandeau global macro (réel) */}
      {(() => {
        const r = macroRegimeState.regime;
        const liq = regimeView(r?.global_liquidity?.regime);
        const rec = r?.indicators?.recession_prob_12m?.value ?? null;
        const realRate = r?.indicators?.real_rate_10y?.value ?? null;
        return (
          <Pressable
            onPress={() => router.push('/macro-cosmique')}
            style={({ pressed }) => [styles.globalStrip, { opacity: pressed ? 0.8 : 1 }]}>
            <View style={styles.globalItem}>
              <Text style={styles.globalLabel}>Liquidité</Text>
              <Text style={[styles.globalValue, { color: liq.color }]}>{liq.label}</Text>
            </View>
            <View style={[styles.globalItem, styles.globalItemMid]}>
              <Text style={styles.globalLabel}>Récession 12m</Text>
              <Text
                style={[
                  styles.globalValue,
                  { color: rec != null && rec >= 0.5 ? Cosmic.neutral : Cosmic.text },
                ]}>
                {rec != null ? `${(rec * 100).toFixed(0)}%` : '—'}
              </Text>
            </View>
            <View style={styles.globalItem}>
              <Text style={styles.globalLabel}>Taux réel 10Y</Text>
              <Text style={styles.globalValue}>
                {realRate != null ? `${realRate.toFixed(2)}%` : '—'}
              </Text>
            </View>
          </Pressable>
        );
      })()}

      {/* Statut de discipline (F1) */}
      <View style={[styles.disciplineCard, { borderColor: discipline.color + '88' }]}>
        <Text style={[styles.disciplineHead, { color: discipline.color }]}>{discipline.head}</Text>
        <Text style={styles.disciplineSub}>
          « Puis-je trader ? » = freins de discipline, PAS un ordre d&apos;achat (aucun edge prouvé).
        </Text>
        {criteria.map((c, i) => (
          <View key={i} style={styles.critRow}>
            <Text style={[styles.critIcon, { color: c.ok ? Cosmic.long : Cosmic.neutral }]}>
              {c.ok ? '✓' : '⚠'}
            </Text>
            <Text style={styles.critText}>{c.text}</Text>
          </View>
        ))}
      </View>

      {/* Dernier signal BTC (priorité) */}
      <Text style={styles.sectionLabel}>Dernier signal BTC</Text>
      <CosmicSignalCard entityId="BTC" signal={latestBtc} loading={kpis.loading} />

      {/* Trades ouverts */}
      {openTrades.length > 0 ? (
        <Pressable
          onPress={() => router.push('/journal')}
          style={({ pressed }) => [styles.openTrades, { opacity: pressed ? 0.8 : 1 }]}>
          <Text style={styles.sectionLabel}>Mes trades ouverts ({openTrades.length})</Text>
          {openTrades.slice(0, 3).map((t) => {
            const dir = directionMeta(t.direction);
            return (
              <View key={t.id} style={styles.openTradeRow}>
                <Text style={styles.openTradeEntity}>{t.entity_id}</Text>
                <Text style={[styles.openTradeDir, { color: dir.color }]}>{dir.label}</Text>
                <Text style={styles.openTradeMeta}>{t.size_lots} lot · @ {t.entry_price}</Text>
              </View>
            );
          })}
          <Text style={styles.openTradesHint}>Ouvrir le Carnet ›</Text>
        </Pressable>
      ) : null}

      {/* Prochain event macro */}
      {nextEvent ? (
        <Pressable
          onPress={() => router.push('/macro')}
          style={({ pressed }) => [styles.nextEvent, { opacity: pressed ? 0.8 : 1 }]}>
          <Text style={styles.nextEventLabel}>📅 Prochain event</Text>
          <Text style={styles.nextEventText} numberOfLines={1}>
            {nextEvent.event_name} · {formatLocal(nextEvent.scheduled_for)}
          </Text>
          <Text style={styles.nextEventChevron}>›</Text>
        </Pressable>
      ) : null}

      {/* --- Contexte (déménagera vers l'onglet Sources) --- */}
      <Text style={styles.contextHeader}>Contexte</Text>
      <BreakingNewsCard />
      <TopHeadlinesCard
        headlines={headlinesState.headlines}
        entityId={headlinesEntity}
        onEntityChange={setHeadlinesEntity}
        displayLimit={5}
        loading={headlinesState.loading}
        error={headlinesState.error}
      />
      <PolymarketCard
        snapshot={polymarketState.snapshot}
        entityId={polymarketEntity}
        onEntityChange={setPolymarketEntity}
        displayLimit={3}
        marketsPerEvent={4}
        loading={polymarketState.loading}
        error={polymarketState.error}
      />
      <DerivativesCard
        snapshot={derivativesState.snapshot}
        loading={derivativesState.loading}
        error={derivativesState.error}
      />
    </>
  );

  // ---------- Calibration (inchangé — déménagera vers Plus) ----------
  const renderCalibrationTab = () => (
    <>
      <HitRateCard
        data={hitRateState.data}
        entityId={hitRateEntity}
        horizon={hitRateHorizon}
        includeFlagged={hitRateIncludeFlagged}
        onEntityChange={setHitRateEntity}
        onHorizonChange={setHitRateHorizon}
        onIncludeFlaggedChange={setHitRateIncludeFlagged}
        loading={hitRateState.loading}
        error={hitRateState.error}
      />
      <HitRateByVeracityCard
        data={hitRateByVeracityState.data}
        entityId={hitRateEntity}
        horizon={hitRateHorizon}
        loading={hitRateByVeracityState.loading}
        error={hitRateByVeracityState.error}
      />
      <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
        <ThemedText type="defaultSemiBold">Tendance veracity</ThemedText>
        {kpis.veracitySeries.length >= 2 ? (
          <>
            <ThemedText style={styles.veracityStats}>
              min {(Math.min(...kpis.veracitySeries) * 100).toFixed(0)}% · actuelle{' '}
              {(kpis.veracitySeries[kpis.veracitySeries.length - 1] * 100).toFixed(0)}% · max{' '}
              {(Math.max(...kpis.veracitySeries) * 100).toFixed(0)}%
            </ThemedText>
            <ThemedText style={styles.veracitySubtitle}>
              {kpis.veracitySeries.length} derniers signaux · ~24 dernières heures
            </ThemedText>
          </>
        ) : null}
        <MiniSparkline
          values={kpis.veracitySeries}
          height={80}
          color={palette.tint}
          thresholds={[0.7]}
          personalThreshold={0.85}
          personalThresholdColor="#27ae60"
          autoScale
          emptyMessage="Pas assez de signaux pour tracer"
        />
      </ThemedView>

      <ThemedView style={styles.section}>
        <ThemedText type="subtitle">Activité 24 h</ThemedText>
        <ThemedView style={styles.kpiRow}>
          <KpiCard title="Total" value={kpis.signalsByHorizon.total.toString()} subtitle="signaux émis" />
          <KpiCard title="Flash" value={kpis.signalsByHorizon.flash.toString()} />
        </ThemedView>
        <ThemedView style={styles.kpiRow}>
          <KpiCard title="Swing" value={kpis.signalsByHorizon.swing.toString()} />
          <KpiCard title="Macro" value={kpis.signalsByHorizon.macro.toString()} />
        </ThemedView>
      </ThemedView>

      <StatsLLMCard stats={kpis.llmStatsToday} loading={kpis.loading} error={kpis.signals24hError} />
    </>
  );

  // ---------- Système (inchangé — déménagera vers Plus) ----------
  const renderSystemTab = () => (
    <>
      <ThemedView style={[styles.statusBox, { borderColor: statusColor[healthState.status] }]}>
        <ThemedView style={styles.statusHeader}>
          <ThemedText type="defaultSemiBold">État du core</ThemedText>
          {healthState.status === 'loading' ? (
            <ActivityIndicator size="small" />
          ) : (
            <ThemedView style={[styles.dot, { backgroundColor: statusColor[healthState.status] }]} />
          )}
        </ThemedView>
        <ThemedText style={{ color: statusColor[healthState.status], fontWeight: '600' }}>
          {statusLabel[healthState.status]}
        </ThemedText>
        {healthState.status === 'ok' && healthState.data ? (
          <ThemedText style={styles.metaText}>
            v{healthState.data.version} · env {healthState.data.env} · {baseUrl}
          </ThemedText>
        ) : healthState.status === 'error' && healthState.error ? (
          <ThemedText style={styles.errorText}>{healthState.error}</ThemedText>
        ) : null}
        <Pressable
          onPress={() => void checkHealth()}
          disabled={healthState.status === 'loading'}
          style={({ pressed }) => [
            styles.refreshBtn,
            { backgroundColor: palette.tint, opacity: pressed || healthState.status === 'loading' ? 0.7 : 1 },
          ]}>
          <ThemedText style={styles.refreshLabel}>Rafraîchir</ThemedText>
        </Pressable>
      </ThemedView>

      <SourceHealthCard />

      <ThemedView style={styles.versionBox}>
        <ThemedText style={styles.versionText}>
          tik-dashboard v{APP_VERSION} — Expo SDK 54
        </ThemedText>
        <ThemedText style={styles.versionText}>
          Identifiants / déconnexion : onglet Config.
        </ThemedText>
      </ThemedView>
    </>
  );

  const tabContent: Record<HomeTab, ReactNode> = {
    market: renderMarketTab(),
    calibration: renderCalibrationTab(),
    system: renderSystemTab(),
  };

  return (
    <CosmicBackground>
      <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + 10 }]}>
        {/* Header cosmique */}
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.brand}>
              Tik<Text style={styles.brandSub}> · cockpit</Text>
            </Text>
            <Text style={styles.brandTag}>Observatoire OSINT</Text>
          </View>
          <View style={styles.headerMeta}>
            <Text style={styles.headerMetaLabel}>État du core</Text>
            <Text style={[styles.headerMetaValue, { color: statusColor[healthState.status] }]}>
              {statusLabel[healthState.status]}
            </Text>
          </View>
        </View>

        {/* Sous-onglets cosmiques */}
        <View style={styles.subTabBar}>
          {TAB_ORDER.map((tab) => {
            const isActive = tab === activeTab;
            return (
              <Pressable
                key={tab}
                onPress={() => setActiveTab(tab)}
                accessibilityRole="tab"
                accessibilityState={{ selected: isActive }}
                style={({ pressed }) => [
                  styles.subTab,
                  {
                    backgroundColor: isActive ? Cosmic.accent : 'transparent',
                    borderColor: isActive ? Cosmic.accent : Cosmic.borderStrong,
                    opacity: pressed ? 0.7 : 1,
                  },
                ]}>
                <Text style={[styles.subTabLabel, { color: isActive ? Cosmic.bgDeep : Cosmic.textDim }]}>
                  {TAB_LABELS[tab]}
                </Text>
              </Pressable>
            );
          })}
        </View>

        {tabContent[activeTab]}
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
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-end',
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
    marginTop: 3,
  },
  headerMeta: {
    alignItems: 'flex-end',
  },
  headerMetaLabel: {
    color: Cosmic.textFaint,
    fontSize: 8,
    letterSpacing: 1,
    textTransform: 'uppercase',
    fontFamily: Fonts.mono,
  },
  headerMetaValue: {
    fontSize: 12,
    fontWeight: '700',
    marginTop: 2,
  },
  subTabBar: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 4,
  },
  subTab: {
    flex: 1,
    paddingVertical: 9,
    borderWidth: 1,
    borderRadius: 999,
    alignItems: 'center',
  },
  subTabLabel: {
    fontSize: 13,
    fontWeight: '700',
  },
  // Bandeau global
  globalStrip: {
    flexDirection: 'row',
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 14,
    paddingVertical: 12,
  },
  globalItem: {
    flex: 1,
    alignItems: 'center',
    gap: 5,
  },
  globalItemMid: {
    borderLeftWidth: 1,
    borderRightWidth: 1,
    borderColor: Cosmic.border,
  },
  globalLabel: {
    color: Cosmic.textFaint,
    fontSize: 8,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    fontFamily: Fonts.mono,
  },
  globalValue: {
    color: Cosmic.text,
    fontSize: 16,
    fontWeight: '700',
    fontFamily: serifTitleFamily,
    fontStyle: 'italic',
  },
  // Discipline
  disciplineCard: {
    backgroundColor: Cosmic.card,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
    gap: 6,
  },
  disciplineHead: {
    fontSize: 15,
    fontWeight: '800',
  },
  disciplineSub: {
    color: Cosmic.textFaint,
    fontSize: 12,
    fontStyle: 'italic',
    marginBottom: 2,
  },
  critRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
  },
  critIcon: {
    fontSize: 13,
    fontWeight: '800',
    width: 14,
  },
  critText: {
    flex: 1,
    color: Cosmic.textDim,
    fontSize: 14,
    lineHeight: 20,
  },
  sectionLabel: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginTop: 4,
  },
  // Trades ouverts
  openTrades: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
    gap: 6,
  },
  openTradeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  openTradeEntity: {
    color: Cosmic.text,
    fontSize: 14,
    fontWeight: '700',
    width: 44,
  },
  openTradeDir: {
    fontSize: 12,
    fontWeight: '800',
    width: 64,
  },
  openTradeMeta: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontFamily: Fonts.mono,
  },
  openTradesHint: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '600',
    textAlign: 'right',
    marginTop: 2,
  },
  // Prochain event
  nextEvent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 11,
    paddingHorizontal: 12,
  },
  nextEventLabel: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontWeight: '600',
  },
  nextEventText: {
    flex: 1,
    color: Cosmic.text,
    fontSize: 13,
  },
  nextEventChevron: {
    color: Cosmic.textDim,
    fontSize: 18,
  },
  contextHeader: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginTop: 10,
  },
  // ----- styles repris (Calibration/Système, thémés sombre) -----
  errorText: { color: '#e87a7a', fontSize: 13 },
  metaText: { fontSize: 12, opacity: 0.6 },
  refreshBtn: { marginTop: 8, paddingVertical: 10, borderRadius: 8, alignItems: 'center' },
  refreshLabel: { color: '#ffffff', fontWeight: '600' },
  card: { marginTop: 4, padding: 16, borderWidth: 1, borderRadius: 12, gap: 8 },
  section: { gap: 12, marginTop: 4 },
  kpiRow: { flexDirection: 'row', gap: 12 },
  veracityStats: { fontSize: 13, opacity: 0.85, marginTop: 2 },
  veracitySubtitle: { fontSize: 11, opacity: 0.5, marginBottom: 4 },
  statusBox: { padding: 16, borderWidth: 1, borderRadius: 12, gap: 8 },
  statusHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  dot: { width: 12, height: 12, borderRadius: 6 },
  versionBox: { marginTop: 16, paddingTop: 12, gap: 4 },
  versionText: { fontSize: 12, opacity: 0.5 },
});
