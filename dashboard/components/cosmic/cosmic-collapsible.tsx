/**
 * CosmicCollapsible — section dépliable sur fond sombre cosmique.
 *
 * Le `Collapsible` partagé (`components/ui/collapsible.tsx`) rend un `ThemedView`
 * dont le fond = `Colors.dark.background` (#0a0c14) : posé dans une carte
 * `Cosmic.card` (#141a2b), il y peindrait un rectangle plus sombre visible. Cette
 * version reste sur fond transparent et utilise les tokens Cosmic, pour rester
 * homogène dans les écrans cosmiques (Config, À propos…).
 */

import { PropsWithChildren, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Cosmic } from '@/constants/cosmic';

export function CosmicCollapsible({ title, children }: PropsWithChildren<{ title: string }>) {
  const [open, setOpen] = useState(false);
  return (
    <View>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        style={({ pressed }) => [styles.heading, { opacity: pressed ? 0.7 : 1 }]}>
        <Text style={[styles.chevron, { transform: [{ rotate: open ? '90deg' : '0deg' }] }]}>›</Text>
        <Text style={styles.title}>{title}</Text>
      </Pressable>
      {open ? <View style={styles.content}>{children}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  heading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 4,
  },
  chevron: {
    color: Cosmic.accent,
    fontSize: 18,
    fontWeight: '700',
    width: 14,
    textAlign: 'center',
  },
  title: {
    color: Cosmic.text,
    fontSize: 14,
    fontWeight: '600',
  },
  content: {
    marginTop: 6,
    marginLeft: 22,
  },
});
