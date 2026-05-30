import type { ReactNode } from 'react';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, StyleSheet } from 'react-native';

import { HitRateByVeracityCard } from '@/components/dashboard/hit-rate-by-veracity-card';
import { HitRateCard } from '@/components/dashboard/hit-rate-card';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { MacroEventsCard } from '@/components/dashboard/macro-events-card';
import { PolymarketCard } from '@/components/dashboard/polymarket-card';
import { MiniSparkline } from '@/components/dashboard/mini-sparkline';
import { SignalFreshnessBanner } from '@/components/dashboard/signal-freshness-banner';
import { SourceHealthCard } from '@/components/dashboard/source-health-card';
import { StatsLLMCard } from '@/components/dashboard/stats-llm-card';
import { TopHeadlinesCard } from '@/components/dashboard/top-headlines-card';
import { VeracityGauge } from '@/components/dashboard/veracity-gauge';
import ParallaxScrollView from '@/components/parallax-scroll-view';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors, Fonts } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { getHealth } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { Health } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';
import { useDashboardKpis } from '@/src/hooks/useDashboardKpis';
import { useHitRate } from '@/src/hooks/useHitRate';
import { useHitRateByVeracity } from '@/src/hooks/useHitRateByVeracity';
import { useTick } from '@/src/hooks/use-tick';
import { useMacroReading } from '@/src/hooks/useMacroReading';
import { useMacroReadingLive } from '@/src/hooks/useMacroReadingLive';
import { usePolymarket } from '@/src/hooks/usePolymarket';
import { useTopHeadlines } from '@/src/hooks/useTopHeadlines';
import { useUpcomingMacroEvents } from '@/src/hooks/useUpcomingMacroEvents';
import { timeAgo } from '@/src/utils/time';

import pkg from '../../package.json';

const APP_VERSION = pkg.version;

const HEALTH_REFRESH_INTERVAL_MS = 30_000;

// Paquet 24 — refonte Home tabs Marché/Calibration/Système (backlog #5 Levier B+D).
// Marché par défaut = vue trading manuel quotidien (Top headlines + Veracity globale +
// Macro events + Dernier signal par actif + Activité 24h).
type HomeTab = 'market' | 'calibration' | 'system';

const TAB_LABELS: Record<HomeTab, string> = {
  market: 'Marché',
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

const INITIAL_HEALTH: HealthState = {
  status: 'idle',
  data: null,
  error: null,
  lastChecked: null,
};

function directionColor(direction: string): string {
  switch (direction) {
    case 'long':
      return '#27ae60';
    case 'short':
      return '#c0392b';
    default:
      return '#7f8c8d';
  }
}

export default function HomeScreen() {
  const { client, baseUrl } = useAuth();
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

  // Polymarket (contexte de marché, shadow) — défaut GOLD : l'or est léger
  // côté signaux Tik, c'est là que ce contexte apporte le plus.
  const [polymarketEntity, setPolymarketEntity] = useState<string>('GOLD');
  const polymarketState = usePolymarket(polymarketEntity, { limit: 4 });
  // Lacune B Phase B1 — calendrier macro/géopolitique 7 j à venir.
  // Cap 4 events sur Home (1 mis en avant + 3 suivants), poll 5 min
  // (cohérent TTL cache Redis 5 min).
  const macroEventsState = useUpcomingMacroEvents({ hours: 7 * 24, limit: 4 });
  const macroReadingState = useMacroReading();
  const macroLiveState = useMacroReadingLive();
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
    idle: palette.icon,
    loading: palette.icon,
    ok: '#27ae60',
    error: '#c0392b',
  };

  const renderEntityCard = (entity: string) => {
    const last = kpis.lastSignalByEntity[entity];
    if (!last) {
      return (
        <KpiCard
          key={entity}
          title={entity}
          value="—"
          subtitle="Pas de signal sur 24 h"
        />
      );
    }
    return (
      <KpiCard
        key={entity}
        title={`${entity} • ${last.horizon}`}
        value={last.direction.toUpperCase()}
        accent={directionColor(last.direction)}
        subtitle={`conf ${(last.confidence * 100).toFixed(0)}% · verac ${(last.veracity * 100).toFixed(0)}% · ${timeAgo(last.timestamp)}`}
      />
    );
  };

  // Marché : vue trading manuel quotidien (cf. backlog #5 Levier B+D).
  const renderMarketTab = () => (
    <>
      <SignalFreshnessBanner />
      <ThemedView style={[styles.disciplineCard, { borderColor: '#e67e22' }]}>
        <ThemedText style={styles.disciplineTitle}>
          ⚠ Avant chaque trade — Tik = contexte, pas un ordre
        </ThemedText>
        <ThemedText style={styles.disciplineLine}>
          • Aucun edge directionnel prouvé (ni BTC ni GOLD) : ne suis pas la flèche mécaniquement, croise avec ton jugement
        </ThemedText>
        <ThemedText style={styles.disciplineLine}>
          • Sizing 1 % du capital max — c&apos;est ta vraie protection
        </ThemedText>
        <ThemedText style={styles.disciplineLine}>
          • Pas de trade ±4h autour d&apos;un event macro HIGH (voir Calendrier macro)
        </ThemedText>
        <ThemedText style={styles.disciplineLine}>
          • Veracity ≥ 85 % (swing BTC) = filtre de bruit, pas une garantie de sens
        </ThemedText>
        <ThemedText style={styles.disciplineLine}>
          • Tik neutral = pas de vue → ne force pas un trade
        </ThemedText>
      </ThemedView>

      <TopHeadlinesCard
        headlines={headlinesState.headlines}
        entityId={headlinesEntity}
        onEntityChange={setHeadlinesEntity}
        displayLimit={5}
        loading={headlinesState.loading}
        error={headlinesState.error}
      />

      <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
        {kpis.veracity ? (
          <>
            <VeracityGauge value={kpis.veracity.global_veracity} status={kpis.veracity.status} />
            <ThemedText style={styles.metaText}>
              {kpis.veracity.sources_count_active} source(s) active(s) · dernière computation {timeAgo(kpis.veracity.last_computed)}
            </ThemedText>
          </>
        ) : kpis.veracityError ? (
          <ThemedText style={styles.errorText}>Veracity indisponible : {kpis.veracityError}</ThemedText>
        ) : kpis.loading ? (
          <ActivityIndicator />
        ) : (
          <ThemedText style={{ opacity: 0.6 }}>Veracity inconnue.</ThemedText>
        )}
      </ThemedView>

      <MacroEventsCard
        events={macroEventsState.events}
        loading={macroEventsState.loading}
        error={macroEventsState.error}
        displayLimit={4}
        readings={macroReadingState.readings}
        live={macroLiveState.live}
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

      <ThemedView style={styles.section}>
        <ThemedText type="subtitle">Dernier signal par actif</ThemedText>
        <ThemedView style={styles.kpiRow}>
          {renderEntityCard('BTC')}
          {renderEntityCard('GOLD')}
        </ThemedView>
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
        {kpis.signals24hError ? (
          <ThemedText style={styles.errorText}>
            Activité indisponible : {kpis.signals24hError}
          </ThemedText>
        ) : null}
      </ThemedView>
    </>
  );

  // Calibration : vue d'audit consultée en début de journée (cf. backlog #5).
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
        <ThemedView style={styles.legendRow}>
          <ThemedText style={styles.legendItem}>
            ligne verte 85 % = ton seuil J+24 (Garde-fou 2-bis transitoire) · tirets gris 70 % = plancher rejet
          </ThemedText>
        </ThemedView>
      </ThemedView>

      <StatsLLMCard
        stats={kpis.llmStatsToday}
        loading={kpis.loading}
        error={kpis.signals24hError}
      />
    </>
  );

  // Système : état du core + version + lien onglets secondaires.
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
            {
              backgroundColor: palette.tint,
              opacity: pressed || healthState.status === 'loading' ? 0.7 : 1,
            },
          ]}>
          <ThemedText style={styles.refreshLabel}>Rafraîchir</ThemedText>
        </Pressable>
      </ThemedView>

      <SourceHealthCard />

      <ThemedView style={styles.versionBox}>
        <ThemedText style={styles.versionText}>
          tik-dashboard v{APP_VERSION} — Expo SDK 54 — plateforme {Platform.OS}
        </ThemedText>
        <ThemedText style={styles.versionText}>
          Pour modifier les credentials ou se déconnecter, voir l’onglet Config.
        </ThemedText>
        <ThemedText style={styles.versionText}>
          Autres onglets : Signals (flux WS) · Watchlist · Alerts · Bots · Config.
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
    <ParallaxScrollView
      headerBackgroundColor={{ light: '#0a7ea4', dark: '#0d2a3d' }}
      headerImage={
        <ThemedText style={[styles.headerLogo, { fontFamily: Fonts.rounded }]}>
          Tik
        </ThemedText>
      }>
      <ThemedView style={styles.titleContainer}>
        <ThemedText type="title">Dashboard</ThemedText>
      </ThemedView>

      <ThemedText>
        Visualisation temps réel des signaux OSINT produits par le core Tik.
      </ThemedText>

      <ThemedView style={styles.tabBar}>
        {TAB_ORDER.map((tab) => {
          const isActive = tab === activeTab;
          return (
            <Pressable
              key={tab}
              onPress={() => setActiveTab(tab)}
              accessibilityRole="tab"
              accessibilityState={{ selected: isActive }}
              style={({ pressed }) => [
                styles.tabButton,
                {
                  backgroundColor: isActive ? palette.tint : 'transparent',
                  borderColor: isActive ? palette.tint : palette.icon,
                  opacity: pressed ? 0.7 : 1,
                },
              ]}>
              <ThemedText
                style={[
                  styles.tabLabel,
                  { color: isActive ? '#ffffff' : palette.text },
                ]}>
                {TAB_LABELS[tab]}
              </ThemedText>
            </Pressable>
          );
        })}
      </ThemedView>

      {tabContent[activeTab]}
    </ParallaxScrollView>
  );
}

const styles = StyleSheet.create({
  headerLogo: {
    color: '#ffffff',
    fontSize: 72,
    lineHeight: 76,
    fontWeight: 'bold',
    bottom: 24,
    left: 24,
    position: 'absolute',
    includeFontPadding: false,
  },
  titleContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  tabBar: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 16,
    marginBottom: 8,
  },
  tabButton: {
    flex: 1,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderRadius: 8,
    alignItems: 'center',
  },
  tabLabel: {
    fontSize: 14,
    fontWeight: '600',
  },
  statusBox: {
    marginTop: 16,
    padding: 16,
    borderWidth: 1,
    borderRadius: 12,
    gap: 8,
  },
  statusHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  dot: {
    width: 12,
    height: 12,
    borderRadius: 6,
  },
  errorText: {
    color: '#c0392b',
    fontSize: 13,
  },
  metaText: {
    fontSize: 12,
    opacity: 0.6,
  },
  refreshBtn: {
    marginTop: 8,
    paddingVertical: 10,
    borderRadius: 8,
    alignItems: 'center',
  },
  refreshLabel: {
    color: '#ffffff',
    fontWeight: '600',
  },
  card: {
    marginTop: 16,
    padding: 16,
    borderWidth: 1,
    borderRadius: 12,
    gap: 8,
  },
  section: {
    gap: 12,
    marginTop: 16,
  },
  kpiRow: {
    flexDirection: 'row',
    gap: 12,
  },
  legendRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
  },
  legendItem: {
    fontSize: 11,
    opacity: 0.5,
  },
  veracityStats: {
    fontSize: 13,
    opacity: 0.85,
    marginTop: 2,
  },
  veracitySubtitle: {
    fontSize: 11,
    opacity: 0.5,
    marginBottom: 4,
  },
  versionBox: {
    marginTop: 24,
    paddingTop: 12,
    gap: 4,
  },
  versionText: {
    fontSize: 12,
    opacity: 0.5,
  },
  disciplineCard: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 6,
    backgroundColor: 'rgba(230, 126, 34, 0.08)',
  },
  disciplineTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: '#e67e22',
    marginBottom: 2,
  },
  disciplineLine: {
    fontSize: 13,
    lineHeight: 18,
  },
});
