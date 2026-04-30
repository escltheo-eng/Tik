import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, StyleSheet } from 'react-native';

import ParallaxScrollView from '@/components/parallax-scroll-view';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors, Fonts } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { getHealth } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { Health } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';

const REFRESH_INTERVAL_MS = 30_000;

interface HealthState {
  status: 'idle' | 'loading' | 'ok' | 'error';
  data: Health | null;
  error: string | null;
  lastChecked: Date | null;
}

const INITIAL_STATE: HealthState = {
  status: 'idle',
  data: null,
  error: null,
  lastChecked: null,
};

export default function HomeScreen() {
  const { client, baseUrl, signOut } = useAuth();
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];

  const [healthState, setHealthState] = useState<HealthState>(INITIAL_STATE);

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
    const run = async () => {
      if (cancelled) return;
      await checkHealth();
    };
    void run();
    const id = setInterval(() => {
      if (!cancelled) void run();
    }, REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [checkHealth]);

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
          <ThemedText type="subtitle">État du core</ThemedText>
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
          <ThemedText>
            Version {healthState.data.version} — env {healthState.data.env}
          </ThemedText>
        ) : null}

        {healthState.status === 'error' && healthState.error ? (
          <ThemedText style={styles.errorText}>{healthState.error}</ThemedText>
        ) : null}

        <ThemedText style={styles.metaText}>
          URL : {baseUrl}
        </ThemedText>

        {healthState.lastChecked ? (
          <ThemedText style={styles.metaText}>
            Dernière vérification : {healthState.lastChecked.toLocaleTimeString()}
          </ThemedText>
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

      <ThemedView style={styles.section}>
        <ThemedText type="subtitle">Roadmap Paquet 3</ThemedText>
        <ThemedText>
          • Session 1 : Bootstrap & Hello World (livrée){'\n'}
          • Session 2 : Auth + client HTTP vers le core (en cours){'\n'}
          • Session 3 : WebSocket live + Signals Feed{'\n'}
          • Session 4 : KPIs Home + Charts{'\n'}
          • Session 5 : Notifications push + polish
        </ThemedText>
      </ThemedView>

      <Pressable
        onPress={() => void signOut()}
        style={({ pressed }) => [
          styles.signOutBtn,
          { borderColor: palette.icon, opacity: pressed ? 0.6 : 1 },
        ]}>
        <ThemedText style={{ color: palette.icon }}>Se déconnecter</ThemedText>
      </Pressable>

      <ThemedView style={styles.versionBox}>
        <ThemedText style={styles.versionText}>
          tik-dashboard v0.3.0 — Expo SDK 54 — plateforme {Platform.OS}
        </ThemedText>
      </ThemedView>
    </ParallaxScrollView>
  );
}

const styles = StyleSheet.create({
  headerLogo: {
    color: '#ffffff',
    fontSize: 96,
    fontWeight: 'bold',
    bottom: 16,
    left: 24,
    position: 'absolute',
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
  section: {
    gap: 8,
    marginTop: 16,
  },
  signOutBtn: {
    marginTop: 24,
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
    borderWidth: 1,
  },
  versionBox: {
    marginTop: 16,
    paddingTop: 12,
  },
  versionText: {
    fontSize: 12,
    opacity: 0.5,
  },
});
