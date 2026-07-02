/**
 * CosmicSourceHealth — santé des sources en « constellation » (refonte γ, bout 6).
 *
 * Chaque source OSINT = un point lumineux : 🟢 vivante / 🟠 en retard / 🔴 muette
 * (halo renforcé si source critique). Tap → détail (fraîcheur + note). Remplace
 * la carte thémée `SourceHealthCard`. Données réelles via `useSourceHealth`.
 */

import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { Cosmic } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import type { SourceHealthItem } from '@/src/api/types';
import { useSourceHealth } from '@/src/hooks/useSourceHealth';

function statusColor(s: string): string {
  if (s === 'ok') return Cosmic.long;
  if (s === 'stale') return Cosmic.neutral;
  return Cosmic.short;
}

function statusLabel(s: string): string {
  if (s === 'ok') return 'Vivante';
  if (s === 'stale') return 'En retard';
  return 'Muette';
}

function prettyName(name: string): string {
  const base = name.replace(/_(btc|gold)$/i, '').replace(/_/g, ' ').trim();
  return base.replace(/\b\w/g, (c) => c.toUpperCase());
}

function ageLabel(age: number | null): string {
  if (age == null) return 'jamais reçue';
  if (age < 60) return `il y a ${Math.round(age)} s`;
  if (age < 3600) return `il y a ${Math.round(age / 60)} min`;
  if (age < 86400) return `il y a ${Math.round(age / 3600)} h`;
  return `il y a ${Math.round(age / 86400)} j`;
}

export function CosmicSourceHealth() {
  const { health, loading } = useSourceHealth();

  if (!health) {
    return (
      <View style={styles.card}>
        <Text style={styles.title}>Constellation des sources</Text>
        <Text style={styles.empty}>{loading ? 'Sondage…' : 'Santé indisponible.'}</Text>
      </View>
    );
  }

  const onDot = (s: SourceHealthItem) => {
    Alert.alert(
      `${prettyName(s.name)}${s.critical ? ' ★' : ''}`,
      `${statusLabel(s.status)} · ${ageLabel(s.age_seconds)}${s.note ? `\n\n${s.note}` : ''}`,
      [{ text: 'OK' }],
    );
  };

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Constellation des sources</Text>
        <Text style={[styles.count, { color: health.any_critical_down ? Cosmic.short : Cosmic.long }]}>
          {health.n_ok}/{health.n_total} vivantes
        </Text>
      </View>

      <View style={styles.sky}>
        {health.sources.map((s) => {
          const color = statusColor(s.status);
          return (
            <Pressable
              key={s.name}
              onPress={() => onDot(s)}
              style={({ pressed }) => [styles.star, { opacity: pressed ? 0.6 : 1 }]}>
              <View
                style={[
                  styles.dot,
                  {
                    backgroundColor: color,
                    shadowColor: color,
                    shadowRadius: s.critical ? 9 : 5,
                  },
                  s.critical ? styles.dotCritical : null,
                ]}
              />
              <Text style={styles.starLabel} numberOfLines={1}>
                {prettyName(s.name)}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <Text style={styles.legend}>
        🟢 vivante · 🟠 en retard · 🔴 muette · ★ critique — tape un point pour le détail
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
    gap: 12,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  title: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  count: {
    fontSize: 13,
    fontWeight: '700',
    fontFamily: Fonts.mono,
  },
  sky: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  star: {
    width: '25%',
    alignItems: 'center',
    gap: 5,
    paddingVertical: 8,
  },
  dot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    shadowOpacity: 0.9,
    shadowOffset: { width: 0, height: 0 },
    elevation: 4,
  },
  dotCritical: {
    width: 14,
    height: 14,
    borderRadius: 7,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.5)',
  },
  starLabel: {
    color: Cosmic.textDim,
    fontSize: 9,
    textAlign: 'center',
    fontFamily: Fonts.mono,
  },
  legend: {
    color: Cosmic.textFaint,
    fontSize: 11,
    lineHeight: 15,
  },
  empty: {
    color: Cosmic.textDim,
    fontSize: 13,
    paddingVertical: 8,
  },
});
