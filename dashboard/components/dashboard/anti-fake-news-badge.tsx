/**
 * AntiFakeNewsBadge — affichage du flag anti fake-news (ADR-011) côté dashboard.
 *
 * Le champ `Signal.circuit_breaker_status` peut prendre 3 valeurs :
 * - `ok` (par défaut) : aucun flag, ce composant retourne null
 * - `degraded` : drapeau **jaune/orange**. La cross-validation a détecté un
 *   désaccord entre sources (ex: 2 sources sentiment qui divergent fortement).
 *   Le signal est émis avec direction inchangée mais à interpréter avec
 *   prudence. **Soft filtering**, cf. ADR-011 et CLAUDE.md Paquet 5.
 * - `tripped` : drapeau **rouge**. Outliers détectés ou désaccord critique.
 *   La direction a été forcée à `neutral` et l'hypothesis préfixée par
 *   "Anti fake-news: ...".
 *
 * 2 modes d'affichage :
 * - `compact` (liste Signals) : pastille colorée + label court "⚠ AFN" / "🚫 AFN"
 * - défaut (détail signal) : carte avec titre, statut traduit FR, explication
 *
 * Lacune G du plan trading manuel J+10 (Phase 1.1).
 */

import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';

export interface AntiFakeNewsBadgeProps {
  status: string;
  /** Mode compact pour la liste Signals (pastille seule). */
  compact?: boolean;
}

interface BadgeContent {
  color: string;
  bgSoft: string;
  shortLabel: string;
  fullLabel: string;
  description: string;
}

function contentFor(status: string): BadgeContent | null {
  if (status === 'degraded') {
    return {
      color: '#e67e22', // orange — drapeau de prudence (jaune trop pâle pour mobile)
      bgSoft: 'rgba(230, 126, 34, 0.12)',
      shortLabel: '⚠ AFN',
      fullLabel: 'Anti fake-news : sources en désaccord',
      description:
        'Au moins 2 sources de sentiment divergent fortement sur ce signal. ' +
        'Direction inchangée, mais à interpréter avec prudence. ' +
        'Cf. ADR-011 anti fake-news.',
    };
  }
  if (status === 'tripped') {
    return {
      color: '#c0392b', // rouge — bloquant
      bgSoft: 'rgba(192, 57, 43, 0.12)',
      shortLabel: '🚫 AFN',
      fullLabel: 'Anti fake-news : bloqué',
      description:
        'Outliers détectés ou désaccord critique entre sources. ' +
        'La direction a été forcée à `neutral` par sécurité. ' +
        'Le signal original est conservé en audit dans l’hypothèse.',
    };
  }
  // status === 'ok' (ou inconnu) → pas de badge
  return null;
}

export function AntiFakeNewsBadge({ status, compact }: AntiFakeNewsBadgeProps) {
  const content = contentFor(status);
  if (content === null) {
    return null;
  }

  if (compact) {
    return (
      <View style={[styles.compactBadge, { backgroundColor: content.color }]}>
        <ThemedText style={styles.compactLabel}>{content.shortLabel}</ThemedText>
      </View>
    );
  }

  return (
    <ThemedView
      style={[styles.fullBadge, { backgroundColor: content.bgSoft, borderColor: content.color }]}>
      <ThemedText style={[styles.fullLabel, { color: content.color }]}>
        {content.fullLabel}
      </ThemedText>
      <ThemedText style={styles.fullDescription}>{content.description}</ThemedText>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  compactBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  compactLabel: {
    color: '#ffffff',
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  fullBadge: {
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    marginTop: 4,
    gap: 4,
  },
  fullLabel: {
    fontWeight: '700',
    fontSize: 13,
  },
  fullDescription: {
    fontSize: 12,
    opacity: 0.85,
  },
});
