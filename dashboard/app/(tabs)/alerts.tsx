import { useRouter } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { Cosmic, TitleShadow, directionMeta, serifTitleFamily } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import { AlertEntry, AlertType, useAlerts } from '@/src/alerts/AlertsContext';
import { useTick } from '@/src/hooks/use-tick';
import { timeAgo } from '@/src/utils/time';

const ALERT_LABELS: Record<AlertType, string> = {
  crash_warning: 'Crash warning',
  fake_news_detected: 'Fake news detected',
  veracity_collapse: 'Effondrement de l’accord',
};

const ALERT_DESCRIPTIONS: Record<AlertType, string> = {
  crash_warning: 'Le signal porte un macro crash warning. À traiter en priorité côté Zeta.',
  fake_news_detected: 'Le circuit breaker n’est plus à "ok" — possible compromission d’une source.',
  veracity_collapse: 'L’accord entre sources du signal est sous 50%. Sources discordantes.',
};

// Couleurs d'alerte ré-accordées à la palette cosmique (douce, sur fond sombre).
const ALERT_COLORS: Record<AlertType, string> = {
  crash_warning: Cosmic.short, // rouge doux — danger marché
  fake_news_detected: '#b794d4', // violet doux — compromission source
  veracity_collapse: Cosmic.neutral, // ambre — sources en désaccord
};

export default function AlertsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { alerts, unreadCount, connected, markAsRead, markAllAsRead, clear } = useAlerts();
  useTick();

  const renderAlert = (alert: AlertEntry) => {
    const color = ALERT_COLORS[alert.type];
    const dir = directionMeta(alert.signalDirection);
    return (
      <Pressable
        key={alert.id}
        onPress={() => {
          markAsRead(alert.id);
          router.push(`/signal-cosmique/${encodeURIComponent(alert.signalId)}`);
        }}
        style={({ pressed }) => [
          styles.row,
          {
            borderLeftColor: color,
            opacity: alert.read ? 0.6 : pressed ? 0.75 : 1,
          },
        ]}>
        <View style={styles.rowHeader}>
          <Text style={[styles.alertTitle, { color }]}>{ALERT_LABELS[alert.type]}</Text>
          <Text style={styles.timestamp}>{timeAgo(alert.receivedAt)}</Text>
        </View>
        <Text style={styles.description}>{ALERT_DESCRIPTIONS[alert.type]}</Text>
        <View style={styles.metaLine}>
          <Text style={styles.metaItem}>{alert.signalEntity}</Text>
          <Text style={styles.metaItem}>{alert.signalHorizon}</Text>
          <Text style={[styles.metaItem, { color: dir.color }]}>{dir.label}</Text>
          <Text style={styles.metaItem}>
            accord {(alert.signalVeracity * 100).toFixed(0)}%
          </Text>
        </View>
      </Pressable>
    );
  };

  return (
    <CosmicBackground>
      <View style={[styles.container, { paddingTop: insets.top + 8 }]}>
        <View style={styles.header}>
          <View style={styles.headerTop}>
            <Text style={styles.title}>Alerts</Text>
            <View style={styles.statusInline}>
              <View
                style={[styles.dot, { backgroundColor: connected ? Cosmic.long : Cosmic.textFaint }]}
              />
              <Text style={[styles.statusText, { color: connected ? Cosmic.long : Cosmic.textFaint }]}>
                {connected ? 'Live' : 'Inactif'}
              </Text>
            </View>
          </View>
          <Text style={styles.subtitle}>
            Événements remarquables détectés sur le flux de signaux WS.{' '}
            {unreadCount > 0 ? `${unreadCount} non lue(s).` : 'Toutes lues.'}
          </Text>
          {alerts.length > 0 ? (
            <View style={styles.actions}>
              <Pressable
                onPress={markAllAsRead}
                style={({ pressed }) => [styles.actionBtn, { opacity: pressed ? 0.6 : 1 }]}>
                <Text style={styles.actionLabel}>Tout marquer comme lu</Text>
              </Pressable>
              <Pressable
                onPress={clear}
                style={({ pressed }) => [styles.actionBtn, { opacity: pressed ? 0.6 : 1 }]}>
                <Text style={styles.actionLabel}>Effacer</Text>
              </Pressable>
            </View>
          ) : null}
        </View>

        {alerts.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>Aucune alerte pour l’instant</Text>
            <Text style={styles.emptyText}>
              Le flux WS est ouvert. Une alerte apparaîtra ici dès qu’un signal portera un crash
              warning, un circuit breaker tripped, ou un accord entre sources sous le seuil de 50 %.
            </Text>
          </View>
        ) : (
          <ScrollView contentContainerStyle={styles.listContent}>
            {alerts.map(renderAlert)}
          </ScrollView>
        )}
      </View>
    </CosmicBackground>
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
  title: {
    ...TitleShadow.glow,
    fontFamily: serifTitleFamily,
    color: Cosmic.text,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 0.3,
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
    color: Cosmic.textDim,
    fontSize: 14,
    lineHeight: 20,
  },
  actions: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 4,
  },
  actionBtn: {
    borderWidth: 1,
    borderColor: Cosmic.borderStrong,
    borderRadius: 16,
    paddingVertical: 6,
    paddingHorizontal: 12,
  },
  actionLabel: {
    color: Cosmic.textDim,
    fontSize: 13,
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
    gap: 12,
  },
  emptyTitle: {
    color: Cosmic.text,
    fontSize: 18,
    fontWeight: '700',
  },
  emptyText: {
    color: Cosmic.textDim,
    textAlign: 'center',
    fontSize: 15,
    lineHeight: 22,
  },
  listContent: {
    paddingBottom: 24,
    gap: 8,
  },
  row: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderLeftWidth: 4,
    borderRadius: 12,
    padding: 12,
    gap: 6,
  },
  rowHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  alertTitle: {
    fontSize: 15,
    fontWeight: '700',
  },
  description: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 18,
  },
  timestamp: {
    color: Cosmic.textFaint,
    fontSize: 11,
  },
  metaLine: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
    marginTop: 4,
  },
  metaItem: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontFamily: Fonts.mono,
    textTransform: 'uppercase',
  },
});
