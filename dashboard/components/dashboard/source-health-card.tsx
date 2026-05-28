/**
 * SourceHealthCard — santé par source OSINT (onglet Système).
 *
 * Complète la bannière M4 (production agrégée) : ici on voit CHAQUE source
 * (fraîcheur de sa clé Redis). ok = à jour, stale = bloquée, missing = ne publie
 * pas (ex. Reddit 403 / Bug 11). L'en-tête n'alarme (rouge) que si une source
 * CRITIQUE est dégradée ; les dégradations connues/non critiques (Reddit, shadow,
 * GOLD) sont listées en gris atténué pour transparence sans crier au loup.
 */

import { StyleSheet } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { useSourceHealth } from '@/src/hooks/useSourceHealth';

const COLOR = { ok: '#27ae60', stale: '#e67e22', missing: '#c0392b', muted: '#95a5a6' };

function dotColor(status: string, critical: boolean): string {
  if (status === 'ok') return COLOR.ok;
  if (status === 'stale') return COLOR.stale;
  return critical ? COLOR.missing : COLOR.muted; // missing
}

function formatAge(seconds: number | null): string {
  if (seconds == null) return 'absente';
  const m = Math.floor(seconds / 60);
  if (m < 60) return `il y a ${m} min`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem > 0 ? `il y a ${h} h ${rem} min` : `il y a ${h} h`;
}

export function SourceHealthCard() {
  const { health, loading } = useSourceHealth();

  if (loading && !health) {
    return (
      <ThemedView style={styles.card}>
        <ThemedText type="defaultSemiBold">Santé des sources OSINT</ThemedText>
        <ThemedText style={styles.foot}>Chargement…</ThemedText>
      </ThemedView>
    );
  }
  if (!health) return null;

  const headerColor = health.any_critical_down ? COLOR.missing : COLOR.ok;

  return (
    <ThemedView style={[styles.card, { borderColor: headerColor }]}>
      <ThemedView style={styles.header}>
        <ThemedText type="defaultSemiBold">Santé des sources OSINT</ThemedText>
        <ThemedView style={[styles.dot, { backgroundColor: headerColor }]} />
      </ThemedView>
      <ThemedText style={[styles.summary, { color: headerColor }]}>
        {health.n_ok} OK · {health.n_stale} en retard · {health.n_missing} absente
        {health.any_critical_down ? ` — ⚠ critique HS : ${health.critical_down.join(', ')}` : ''}
      </ThemedText>

      {health.sources.map((s) => {
        const degraded = s.status !== 'ok';
        return (
          <ThemedView key={s.name} style={[styles.row, degraded && !s.critical ? styles.dim : null]}>
            <ThemedView style={[styles.rowDot, { backgroundColor: dotColor(s.status, s.critical) }]} />
            <ThemedView style={styles.rowText}>
              <ThemedText style={styles.rowName}>
                {s.name}
                {s.critical ? ' · critique' : ''}
              </ThemedText>
              <ThemedText style={styles.rowMeta}>
                {s.status === 'ok' ? formatAge(s.age_seconds) : `${s.status} — ${s.note}`}
              </ThemedText>
            </ThemedView>
          </ThemedView>
        );
      })}
      <ThemedText style={styles.foot}>
        Détection de dégradation silencieuse — complète la bannière de fraîcheur (M4).
      </ThemedText>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: '#888',
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
    gap: 6,
  },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  dot: { width: 12, height: 12, borderRadius: 6 },
  summary: { fontSize: 13, fontWeight: '600' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 2 },
  dim: { opacity: 0.55 },
  rowDot: { width: 8, height: 8, borderRadius: 4 },
  rowText: { flex: 1, gap: 1 },
  rowName: { fontSize: 13, fontWeight: '600' },
  rowMeta: { fontSize: 11, opacity: 0.75 },
  foot: { fontSize: 11, opacity: 0.6, marginTop: 4 },
});
