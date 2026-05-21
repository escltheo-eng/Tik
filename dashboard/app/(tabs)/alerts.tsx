import { useRouter } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { AlertEntry, AlertType, useAlerts } from '@/src/alerts/AlertsContext';
import { useTick } from '@/src/hooks/use-tick';
import { timeAgo } from '@/src/utils/time';

const ALERT_LABELS: Record<AlertType, string> = {
  crash_warning: 'Crash warning',
  fake_news_detected: 'Fake news detected',
  veracity_collapse: 'Veracity collapse',
};

const ALERT_DESCRIPTIONS: Record<AlertType, string> = {
  crash_warning: 'Le signal porte un macro crash warning. À traiter en priorité côté Zeta.',
  fake_news_detected: 'Le circuit breaker n’est plus à "ok" — possible compromission d’une source.',
  veracity_collapse: 'La veracity du signal est sous le seuil de 50%. Sources discordantes.',
};

const ALERT_COLORS: Record<AlertType, string> = {
  crash_warning: '#c0392b',
  fake_news_detected: '#8e44ad',
  veracity_collapse: '#e67e22',
};

export default function AlertsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];
  const { alerts, unreadCount, connected, markAsRead, markAllAsRead, clear } = useAlerts();
  useTick();

  const renderAlert = (alert: AlertEntry) => {
    const color = ALERT_COLORS[alert.type];
    return (
      <Pressable
        key={alert.id}
        onPress={() => {
          markAsRead(alert.id);
          router.push(`/signal/${encodeURIComponent(alert.signalId)}`);
        }}
        style={({ pressed }) => [
          styles.row,
          {
            borderColor: alert.read ? palette.icon : color,
            borderLeftWidth: 4,
            borderLeftColor: color,
            backgroundColor: pressed ? (colorScheme === 'dark' ? '#1a1d20' : '#f5f5f5') : 'transparent',
            opacity: alert.read ? 0.65 : 1,
          },
        ]}>
        <View style={styles.rowHeader}>
          <ThemedText type="defaultSemiBold" style={{ color }}>
            {ALERT_LABELS[alert.type]}
          </ThemedText>
          <ThemedText style={styles.timestamp}>{timeAgo(alert.receivedAt)}</ThemedText>
        </View>
        <ThemedText style={styles.description}>{ALERT_DESCRIPTIONS[alert.type]}</ThemedText>
        <View style={styles.metaLine}>
          <ThemedText style={styles.metaItem}>{alert.signalEntity}</ThemedText>
          <ThemedText style={styles.metaItem}>{alert.signalHorizon}</ThemedText>
          <ThemedText style={styles.metaItem}>
            {alert.signalDirection.toUpperCase()}
          </ThemedText>
          <ThemedText style={styles.metaItem}>
            verac {(alert.signalVeracity * 100).toFixed(0)}%
          </ThemedText>
        </View>
      </Pressable>
    );
  };

  return (
    <ThemedView style={[styles.container, { paddingTop: insets.top + 8 }]}>
      <View style={styles.header}>
        <View style={styles.headerTop}>
          <ThemedText type="title">Alerts</ThemedText>
          <View style={styles.statusInline}>
            <View style={[styles.dot, { backgroundColor: connected ? '#27ae60' : '#7f8c8d' }]} />
            <ThemedText style={[styles.statusText, { color: connected ? '#27ae60' : '#7f8c8d' }]}>
              {connected ? 'Live' : 'Inactif'}
            </ThemedText>
          </View>
        </View>
        <ThemedText style={styles.subtitle}>
          Événements remarquables détectés sur le flux de signaux WS. {unreadCount > 0 ? `${unreadCount} non lue(s).` : 'Toutes lues.'}
        </ThemedText>
        {alerts.length > 0 ? (
          <View style={styles.actions}>
            <Pressable
              onPress={markAllAsRead}
              style={({ pressed }) => [
                styles.actionBtn,
                { borderColor: palette.icon, opacity: pressed ? 0.6 : 1 },
              ]}>
              <ThemedText style={{ color: palette.text, fontSize: 13 }}>Tout marquer comme lu</ThemedText>
            </Pressable>
            <Pressable
              onPress={clear}
              style={({ pressed }) => [
                styles.actionBtn,
                { borderColor: palette.icon, opacity: pressed ? 0.6 : 1 },
              ]}>
              <ThemedText style={{ color: palette.text, fontSize: 13 }}>Effacer</ThemedText>
            </Pressable>
          </View>
        ) : null}
      </View>

      {alerts.length === 0 ? (
        <ThemedView style={styles.empty}>
          <ThemedText style={styles.emptyTitle}>Aucune alerte pour l’instant</ThemedText>
          <ThemedText style={styles.emptyText}>
            Le flux WS est ouvert. Une alerte apparaîtra ici dès qu’un signal portera un crash warning, un circuit breaker tripped, ou une veracity sous le seuil de 50 %.
          </ThemedText>
        </ThemedView>
      ) : (
        <ScrollView contentContainerStyle={styles.listContent}>
          {alerts.map(renderAlert)}
        </ScrollView>
      )}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingHorizontal: 16,
  },
  header: {
    paddingBottom: 12,
    gap: 8,
  },
  headerTop: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  statusInline: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
  },
  dot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  subtitle: {
    fontSize: 13,
    opacity: 0.7,
  },
  actions: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 4,
  },
  actionBtn: {
    borderWidth: 1,
    borderRadius: 16,
    paddingVertical: 6,
    paddingHorizontal: 12,
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
    gap: 12,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '600',
  },
  emptyText: {
    textAlign: 'center',
    opacity: 0.6,
    fontSize: 14,
    lineHeight: 20,
  },
  listContent: {
    paddingBottom: 24,
    gap: 8,
  },
  row: {
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    gap: 6,
  },
  rowHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  description: {
    fontSize: 13,
    opacity: 0.8,
  },
  timestamp: {
    fontSize: 11,
    opacity: 0.6,
  },
  metaLine: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
    marginTop: 4,
  },
  metaItem: {
    fontSize: 11,
    opacity: 0.6,
    textTransform: 'uppercase',
  },
});
