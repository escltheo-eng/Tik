import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, StyleSheet } from 'react-native';

import { KpiCard } from '@/components/dashboard/kpi-card';
import { MiniSparkline } from '@/components/dashboard/mini-sparkline';
import { StatsLLMCard } from '@/components/dashboard/stats-llm-card';
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
import { timeAgo } from '@/src/utils/time';

const APP_VERSION = '0.5.1';

const HEALTH_REFRESH_INTERVAL_MS = 30_000;

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
              backgroundColor: Colors.light.tint,
              opacity: pressed || healthState.status === 'loading' ? 0.7 : 1,
            },
          ]}>
          <ThemedText style={styles.refreshLabel}>Rafraîchir</ThemedText>
        </Pressable>
      </ThemedView>

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

      <StatsLLMCard
        stats={kpis.llmStatsToday}
        loading={kpis.loading}
        error={kpis.signals24hError}
      />

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

      <ThemedView style={styles.section}>
        <ThemedText type="subtitle">Dernier signal par actif</ThemedText>
        <ThemedView style={styles.kpiRow}>
          {renderEntityCard('BTC')}
          {renderEntityCard('GOLD')}
        </ThemedView>
      </ThemedView>

      <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
        <ThemedText type="defaultSemiBold">Tendance veracity (12 derniers)</ThemedText>
        <MiniSparkline
          values={kpis.veracitySeries}
          color={Colors.light.tint}
          thresholds={[0.7, 0.85]}
          emptyMessage="Pas assez de signaux pour tracer"
        />
        <ThemedView style={styles.legendRow}>
          <ThemedText style={styles.legendItem}>tirets : seuils 0,70 et 0,85</ThemedText>
        </ThemedView>
      </ThemedView>

      <ThemedView style={styles.section}>
        <ThemedText type="subtitle">Roadmap Paquet 3</ThemedText>
        <ThemedText>
          • Session 1 : Bootstrap & Hello World (livrée){'\n'}
          • Session 2 : Auth + client HTTP (livrée){'\n'}
          • Session 3 : WebSocket + Signals Feed (livrée){'\n'}
          • Session 4 : KPIs Home + Charts (livrée){'\n'}
          • Session 5 : Alerts + Bots + Config + Push (en cours)
        </ThemedText>
      </ThemedView>

      <ThemedView style={styles.versionBox}>
        <ThemedText style={styles.versionText}>
          tik-dashboard v{APP_VERSION} — Expo SDK 54 — plateforme {Platform.OS}
        </ThemedText>
        <ThemedText style={styles.versionText}>
          Pour modifier les credentials ou se déconnecter, voir l’onglet Config.
        </ThemedText>
      </ThemedView>
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
  versionBox: {
    marginTop: 24,
    paddingTop: 12,
    gap: 4,
  },
  versionText: {
    fontSize: 12,
    opacity: 0.5,
  },
});
