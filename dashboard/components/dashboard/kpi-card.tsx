import { StyleSheet, type ViewProps } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';

export interface KpiCardProps {
  title: string;
  value: string;
  subtitle?: string;
  accent?: string;
  style?: ViewProps['style'];
}

export function KpiCard({ title, value, subtitle, accent, style }: KpiCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];
  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }, style]}>
      <ThemedText style={styles.title}>{title}</ThemedText>
      <ThemedText type="title" style={[styles.value, accent ? { color: accent } : undefined]}>
        {value}
      </ThemedText>
      {subtitle ? (
        <ThemedText style={styles.subtitle} numberOfLines={2}>
          {subtitle}
        </ThemedText>
      ) : null}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 4,
    // Augmenté de 96 → 110 pour accommoder un subtitle sur 2 lignes
    // (cas "Dernier signal par actif" avec conf + verac + il y a X min).
    minHeight: 110,
  },
  title: {
    fontSize: 12,
    opacity: 0.7,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  value: {
    fontSize: 28,
    lineHeight: 32,
  },
  subtitle: {
    fontSize: 12,
    opacity: 0.6,
    lineHeight: 16,
  },
});
