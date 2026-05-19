import { Alert, Pressable, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { GLOSSARY } from '@/src/glossary';

type GlossaryKey = keyof typeof GLOSSARY;

export interface InfoTooltipProps {
  entryKey: GlossaryKey;
  size?: 'sm' | 'md';
}

export function InfoTooltip({ entryKey, size = 'sm' }: InfoTooltipProps) {
  const entry = GLOSSARY[entryKey];
  if (!entry) return null;

  const onPress = () => {
    const body = entry.ref ? `${entry.short}\n\n— ${entry.ref}` : entry.short;
    Alert.alert(entry.term, body, [{ text: 'OK', style: 'default' }]);
  };

  const dot = size === 'md' ? styles.dotMd : styles.dotSm;
  const label = size === 'md' ? styles.labelMd : styles.labelSm;

  return (
    <Pressable
      onPress={onPress}
      hitSlop={8}
      accessibilityRole="button"
      accessibilityLabel={`Définition de ${entry.term}`}>
      <View style={[styles.dot, dot]}>
        <ThemedText style={label}>?</ThemedText>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  dot: {
    borderRadius: 999,
    backgroundColor: 'rgba(127, 140, 141, 0.25)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  dotSm: {
    width: 16,
    height: 16,
  },
  dotMd: {
    width: 20,
    height: 20,
  },
  labelSm: {
    fontSize: 10,
    lineHeight: 12,
    fontWeight: '700',
    opacity: 0.75,
  },
  labelMd: {
    fontSize: 12,
    lineHeight: 14,
    fontWeight: '700',
    opacity: 0.75,
  },
});
