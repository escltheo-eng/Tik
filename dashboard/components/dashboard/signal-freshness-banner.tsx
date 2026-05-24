/**
 * SignalFreshnessBanner — bandeau rouge si Tik a cessé de produire des signaux.
 *
 * M4 (audit 2026-05-24). Une panne silencieuse (scheduler bloqué, engines en
 * erreur à chaque cycle, ingesters morts) était jusqu'ici avalée en log que
 * personne ne lit. Ce bandeau la rend visible. N'affiche RIEN quand tout va
 * bien (zéro bruit visuel).
 */

import { StyleSheet } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { useSignalFreshness } from '@/src/hooks/useSignalFreshness';

function formatAge(seconds: number | null): string {
  if (seconds == null) return 'jamais';
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem > 0 ? `${h} h ${rem} min` : `${h} h`;
}

export function SignalFreshnessBanner() {
  const { freshness } = useSignalFreshness();
  if (!freshness || !freshness.stale) return null;

  return (
    <ThemedView style={styles.banner}>
      <ThemedText style={styles.title}>⚠ Tik est peut-être en panne</ThemedText>
      <ThemedText style={styles.body}>
        {freshness.last_signal_at
          ? `Aucun nouveau signal depuis ${formatAge(freshness.age_seconds)}. En temps normal, un signal swing BTC est publié toutes les 15 min.`
          : `Aucun signal trouvé en base — le pipeline ne produit rien.`}
      </ThemedText>
      <ThemedText style={styles.hint}>
        Vérifie l&apos;état du core (onglet Système) ou les logs serveur.
      </ThemedText>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  banner: {
    borderWidth: 1,
    borderColor: '#c0392b',
    backgroundColor: 'rgba(192, 57, 43, 0.12)',
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
    gap: 4,
  },
  title: { color: '#c0392b', fontWeight: '700', fontSize: 15 },
  body: { fontSize: 13 },
  hint: { fontSize: 12, opacity: 0.7 },
});
