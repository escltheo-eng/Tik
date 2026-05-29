/**
 * MacroReadingCard — « Lecture macro » éditoriale (SHADOW, contexte).
 *
 * Deux couches CLAIREMENT distinctes (cf. backend /macro_reading) :
 *   🔗 LE MÉCANISME  — savoir général curé, hedgé (PAS mesuré par Tik) :
 *      chaîne causale + actifs typiquement en jeu (USD/or/pétrole/actions…)
 *      + caveat régime-dépendance OBLIGATOIRE (anti-mythe « X monte donc Y chute »).
 *   📊 MESURÉ PAR TIK — réaction historique réelle BTC/OR (ou « n/a »).
 *
 * Pédagogie, pas prédiction : aucun edge revendiqué. Sélecteur d'event pour
 * explorer (culture trading). Pétrole/actions = éducatif → à trader ailleurs.
 */

import { useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { MacroAssetReaction, MacroReading } from '@/src/api/types';

export interface MacroReadingCardProps {
  readings: MacroReading[];
  loading?: boolean;
  error?: string | null;
}

function shortLabel(code: string): string {
  if (code.startsWith('FOMC')) return 'FOMC';
  return code;
}

function importanceColor(imp: string): string {
  switch (imp) {
    case 'HIGH':
      return '#c0392b';
    case 'MEDIUM':
      return '#e67e22';
    default:
      return '#7f8c8d';
  }
}

function signedPct(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;
}

/** Ligne compacte d'un actif : jour + 3j (médiane + % haussier). '' si rien. */
function assetLine(ar: MacroAssetReaction | null): string {
  if (!ar) return '';
  const parts: string[] = [];
  if (ar.same_day) parts.push(`jour ${signedPct(ar.same_day.median)}`);
  if (ar.d3) parts.push(`3j ${signedPct(ar.d3.median)} ↑${Math.round(ar.d3.pct_up)}%`);
  return parts.join('  ·  ');
}

export function MacroReadingCard({ readings, loading, error }: MacroReadingCardProps) {
  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];

  const [selected, setSelected] = useState<string | null>(null);
  const current = useMemo(() => {
    if (readings.length === 0) return null;
    const pick = selected ?? 'CPI';
    return readings.find((r) => r.event_code === pick) ?? readings[0];
  }, [readings, selected]);

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Lecture macro</ThemedText>
        <ThemedText style={styles.periodLabel}>éducatif · contexte</ThemedText>
      </ThemedView>

      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : loading && readings.length === 0 ? (
        <ThemedView style={[styles.loading, { backgroundColor: 'transparent' }]}>
          <ActivityIndicator size="small" />
        </ThemedView>
      ) : !current ? (
        <ThemedText style={styles.emptyLabel}>Aucune lecture disponible.</ThemedText>
      ) : (
        <>
          <ThemedView style={[styles.selector, { backgroundColor: 'transparent' }]}>
            {readings.map((r) => {
              const active = r.event_code === current.event_code;
              return (
                <Pressable
                  key={r.event_code}
                  onPress={() => setSelected(r.event_code)}
                  style={({ pressed }) => [
                    styles.selectorBtn,
                    {
                      backgroundColor: active ? palette.tint : 'transparent',
                      borderColor: palette.icon,
                      opacity: pressed ? 0.7 : 1,
                    },
                  ]}>
                  <ThemedText
                    style={[styles.selectorLabel, { color: active ? '#ffffff' : palette.text }]}>
                    {shortLabel(r.event_code)}
                  </ThemedText>
                </Pressable>
              );
            })}
          </ThemedView>

          <ThemedView style={[styles.headlineRow, { backgroundColor: 'transparent' }]}>
            <ThemedView
              style={[styles.impDot, { backgroundColor: importanceColor(current.importance) }]}
            />
            <ThemedText style={styles.oneLiner}>{current.one_liner}</ThemedText>
          </ThemedView>

          {/* Couche 1 — mécanisme éducatif */}
          <ThemedText style={styles.sectionLabel}>🔗 LE MÉCANISME (théorie générale)</ThemedText>
          <ThemedText style={styles.mechanism}>{current.mechanism}</ThemedText>
          <ThemedText style={styles.assets}>
            Actifs en jeu : {current.assets_in_play.join(' · ')}
          </ThemedText>
          <ThemedText style={styles.caveat}>⚠ {current.regime_caveat}</ThemedText>

          {/* Couche 2 — mesuré par Tik */}
          <ThemedText style={styles.sectionLabel}>
            📊 MESURÉ PAR TIK (BTC/OR{current.measured_available ? ` · ~${current.n_dates} cas` : ''})
          </ThemedText>
          {current.measured_available && (current.btc || current.gold) ? (
            <ThemedView style={{ backgroundColor: 'transparent', gap: 2 }}>
              <ThemedText style={styles.measuredRow}>BTC  {assetLine(current.btc) || '—'}</ThemedText>
              <ThemedText style={styles.measuredRow}>OR   {assetLine(current.gold) || '—'}</ThemedText>
            </ThemedView>
          ) : (
            <ThemedText style={styles.measuredNa}>
              Pas encore mesuré pour cet event (réaction Tik n/a).
            </ThemedText>
          )}

          <ThemedText style={styles.footer}>
            Savoir général hedgé + données mesurées BTC/OR. Contexte, pas une prédiction.
          </ThemedText>
        </>
      )}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 12, padding: 16, gap: 8 },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 4,
  },
  periodLabel: { fontSize: 12, opacity: 0.6 },
  loading: { alignItems: 'center', paddingVertical: 16 },
  emptyLabel: { opacity: 0.6, paddingVertical: 8 },
  errorText: { color: '#c0392b', fontSize: 13 },
  selector: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  selectorBtn: { paddingHorizontal: 12, paddingVertical: 5, borderRadius: 16, borderWidth: 1 },
  selectorLabel: { fontSize: 12, fontWeight: '600', letterSpacing: 0.3 },
  headlineRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 2 },
  impDot: { width: 8, height: 8, borderRadius: 4 },
  oneLiner: { flex: 1, fontSize: 14, fontWeight: '600', lineHeight: 18 },
  sectionLabel: { fontSize: 11, fontWeight: '700', letterSpacing: 0.4, opacity: 0.7, marginTop: 6 },
  mechanism: { fontSize: 13, lineHeight: 19 },
  assets: { fontSize: 12, opacity: 0.8, fontWeight: '600' },
  caveat: { fontSize: 11, opacity: 0.65, fontStyle: 'italic', lineHeight: 15 },
  measuredRow: { fontSize: 13, fontVariant: ['tabular-nums'] },
  measuredNa: { fontSize: 12, opacity: 0.6, fontStyle: 'italic' },
  footer: { fontSize: 11, opacity: 0.55, fontStyle: 'italic', marginTop: 4 },
});
