/**
 * CosmicSection — section repliable pour regrouper des cartes de CONTEXTE par
 * famille (refonte navigation, Stage 1).
 *
 * Pourquoi : la page « Macro » accumulait 8 cartes empilées (« déversoir »,
 * ~1200px de scroll). On les regroupe en familles repliables (titre + sous-titre
 * + chevron) pour réduire le scroll et rendre la logique métier lisible.
 *
 * CONTEXTE STRICT inchangé (Axe #1) : on ne fait que (dé)plier de l'AFFICHAGE.
 * Rien ici ne touche les signaux, la veracity, la direction ou le combined_bias.
 */
import { useState, type PropsWithChildren } from 'react';
import {
  LayoutAnimation,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  UIManager,
  View,
} from 'react-native';

import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';

// Animation de pliage fluide sur Android (no-op sur iOS, déjà natif).
if (
  Platform.OS === 'android' &&
  UIManager.setLayoutAnimationEnabledExperimental
) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

export function CosmicSection({
  title,
  subtitle,
  defaultOpen = false,
  children,
}: PropsWithChildren<{ title: string; subtitle?: string; defaultOpen?: boolean }>) {
  const [open, setOpen] = useState(defaultOpen);

  const toggle = () => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setOpen((v) => !v);
  };

  return (
    <View style={styles.section}>
      <Pressable
        onPress={toggle}
        style={({ pressed }) => [styles.header, { opacity: pressed ? 0.7 : 1 }]}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={`${title}${subtitle ? ' — ' + subtitle : ''}`}>
        <View style={styles.headerText}>
          <Text style={styles.title}>{title}</Text>
          {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
        </View>
        <Text style={styles.chevron}>{open ? '▾' : '▸'}</Text>
      </Pressable>
      {open ? <View style={styles.body}>{children}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: 10,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderWidth: 1,
    borderColor: Cosmic.borderStrong,
    borderRadius: 12,
    backgroundColor: Cosmic.cardAlt,
    paddingVertical: 12,
    paddingHorizontal: 14,
  },
  headerText: {
    flex: 1,
    gap: 2,
  },
  title: {
    ...TitleShadow.soft,
    fontFamily: serifTitleFamily,
    color: Cosmic.text,
    fontSize: 17,
    fontWeight: '700',
    letterSpacing: 0.2,
  },
  subtitle: {
    color: Cosmic.textDim,
    fontSize: 12,
    lineHeight: 16,
  },
  chevron: {
    color: Cosmic.accent,
    fontSize: 16,
    fontWeight: '700',
    marginLeft: 10,
  },
  body: {
    gap: 12,
  },
});
