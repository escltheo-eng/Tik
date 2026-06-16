/**
 * CosmicSignalCard — carte signal « signal d'abord » (échantillon refonte γ).
 *
 * Objectif ergonomie : l'info de décision EN HAUT et lisible d'un coup d'œil
 * (direction + conviction + veracity + amplitude), puis le « pourquoi »
 * (evidence sourcée) et le contre-scénario (philosophie paranoïa contrôlée).
 *
 * 100 % données RÉELLES (aucun champ inventé) : direction, confidence
 * (= conviction OSINT), veracity, advisory.expected_amplitude_pct, evidence[],
 * counter_scenarios[]. Pas de « prix / change % » : ce champ N'EXISTE PAS dans
 * un Signal (cf. types.ts) → on ne l'affiche pas plutôt que de l'inventer.
 *
 * Anti vernis de certitude : un rappel discret « contexte, pas un ordre » reste
 * visible (NO-GO directionnel intact).
 */

import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Defs, RadialGradient, Stop } from 'react-native-svg';

import { Cosmic, TitleShadow, directionMeta, sunColor } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import type { Signal } from '@/src/api/types';
import { amplitudeDisplay, horizonLabel } from '@/src/utils/amplitude';
import { timeAgo } from '@/src/utils/time';

interface Props {
  entityId: string;
  signal: Signal | null;
  loading?: boolean;
  /**
   * - `'summary'` (défaut) : carte riche autoporteuse. Cliquable (tap → page
   *   détail), avec le teaser « Pourquoi » (top 3 evidence) + contre-scénario +
   *   lien « toucher pour le détail ». Pour un usage liste / home.
   * - `'detail'` : héros en haut de la page détail elle-même. NON cliquable, et
   *   sans le teaser evidence/contre-scénario/lien — ces sections sont rendues
   *   EN ENTIER plus bas sur la page, on évite ainsi le doublon.
   */
  variant?: 'summary' | 'detail';
}

/** Mini-soleil lumineux (halo radial SVG) propre à l'actif. */
function MiniSun({ color, size = 40 }: { color: string; size?: number }) {
  const id = `sun-${color.replace('#', '')}`;
  return (
    <Svg width={size} height={size}>
      <Defs>
        <RadialGradient id={id} cx="50%" cy="50%" r="50%">
          <Stop offset="0%" stopColor={color} stopOpacity={1} />
          <Stop offset="45%" stopColor={color} stopOpacity={0.85} />
          <Stop offset="100%" stopColor={color} stopOpacity={0} />
        </RadialGradient>
      </Defs>
      <Circle cx={size / 2} cy={size / 2} r={size / 2} fill={`url(#${id})`} />
    </Svg>
  );
}

/** Source brute → libellé lisible court (ex. "google_news_btc" → "Google News"). */
function prettySource(source: string): string {
  const base = source.replace(/_(btc|gold)$/i, '').replace(/_/g, ' ').trim();
  const map: Record<string, string> = {
    'fear greed': 'Fear & Greed',
    'google news': 'Google News',
    'cryptocompare news': 'CryptoCompare',
    reddit: 'Reddit',
    gdelt: 'GDELT',
    dxy: 'DXY',
    cot: 'COT',
  };
  return map[base.toLowerCase()] ?? base.replace(/\b\w/g, (c) => c.toUpperCase());
}

export function CosmicSignalCard({ entityId, signal, loading, variant = 'summary' }: Props) {
  const sun = sunColor(entityId);
  const router = useRouter();
  const isDetail = variant === 'detail';

  // --- État vide (pas de signal récent) ---
  if (!signal) {
    return (
      <View style={styles.card}>
        <View style={styles.headerRow}>
          <MiniSun color={sun} />
          <Text style={styles.assetName}>{entityId}</Text>
        </View>
        <Text style={styles.emptyText}>
          {loading ? 'Chargement du dernier signal…' : 'Aucun signal sur les dernières 24 h.'}
        </Text>
      </View>
    );
  }

  const dir = directionMeta(signal.direction);
  const convictionPct = Math.round(signal.confidence * 100);
  const veracityPct = Math.round(signal.veracity * 100);
  const amp = amplitudeDisplay(
    entityId,
    signal.horizon,
    signal.advisory?.expected_amplitude_pct,
    signal.advisory?.ref_price,
  );

  const topEvidence = [...(signal.evidence ?? [])]
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);
  const counter = signal.counter_scenarios?.[0] ?? null;

  return (
    <Pressable
      onPress={isDetail ? undefined : () => router.push(`/signal-cosmique/${encodeURIComponent(signal.id)}`)}
      disabled={isDetail}
      style={({ pressed }) => [
        styles.card,
        { borderColor: dir.color + '55', opacity: pressed ? 0.85 : 1 },
      ]}>
      {/* Halo d'ambiance derrière l'en-tête */}
      <View style={[styles.glow, { backgroundColor: dir.color }]} pointerEvents="none" />

      {/* En-tête : mini-soleil + actif + horizon */}
      <View style={styles.headerRow}>
        <MiniSun color={sun} />
        <Text style={styles.assetName}>{entityId}</Text>
        <View style={styles.spacer} />
        <View style={styles.horizonBadge}>
          <Text style={styles.horizonText}>{horizonLabel(signal.horizon)}</Text>
        </View>
        {isDetail ? null : <Text style={styles.chevron}>›</Text>}
      </View>

      {/* Bloc décision : direction + conviction */}
      <View style={styles.decisionRow}>
        <Text style={[styles.direction, { color: dir.color }]}>{dir.label}</Text>
        <Text style={styles.conviction}>Conviction OSINT · {convictionPct}%</Text>
      </View>

      {/* Mini-grille de lecture rapide */}
      <View style={styles.statGrid}>
        <View style={styles.statCell}>
          <Text style={styles.statLabel}>Accord sources</Text>
          <Text style={styles.statValue}>{veracityPct}%</Text>
        </View>
        <View style={styles.statCell}>
          <Text style={styles.statLabel}>Amplitude typique</Text>
          <Text style={styles.statValue}>{amp ? amp.pctLabel : '—'}</Text>
        </View>
        <View style={styles.statCell}>
          <Text style={styles.statLabel}>Émis</Text>
          <Text style={styles.statValue}>{timeAgo(signal.timestamp)}</Text>
        </View>
      </View>

      {/* Pourquoi : evidence sourcée (teaser — masqué sur la page détail, où la
          section Evidence complète est rendue dessous) */}
      {!isDetail && topEvidence.length > 0 ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Pourquoi</Text>
          {topEvidence.map((ev, i) => (
            <View key={i} style={styles.driverRow}>
              <Text style={styles.driverDot}>•</Text>
              <Text style={styles.driverText}>{ev.fact}</Text>
              <View style={styles.sourceChip}>
                <Text style={styles.sourceChipText}>{prettySource(ev.source)}</Text>
              </View>
            </View>
          ))}
        </View>
      ) : null}

      {/* Contre-scénario : ce qui invaliderait le signal (teaser — masqué sur la
          page détail, où tous les contre-scénarios sont listés dessous) */}
      {!isDetail && counter ? (
        <View style={styles.counterBox}>
          <Text style={styles.counterTitle}>
            ⚠ Contre-scénario · {Math.round(counter.probability * 100)}%
          </Text>
          <Text style={styles.counterName}>{counter.name}</Text>
          {counter.mitigation ? (
            <Text style={styles.counterMitigation}>À surveiller : {counter.mitigation}</Text>
          ) : null}
        </View>
      ) : null}

      {/* Affordance de navigation (drill-down) — inutile sur la page détail */}
      {isDetail ? null : (
        <Text style={styles.detailHint}>Toucher la carte pour le détail complet →</Text>
      )}

      {/* Rappel discipline (anti vernis de certitude) */}
      <Text style={styles.disclaimer}>
        Tik = contexte, pas un ordre · aucun edge prouvé · sizing 1 %
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 18,
    padding: 18,
    marginBottom: 16,
    overflow: 'hidden',
  },
  glow: {
    position: 'absolute',
    top: -70,
    right: -50,
    width: 180,
    height: 180,
    borderRadius: 90,
    opacity: 0.1,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  assetName: {
    ...TitleShadow.glow,
    color: Cosmic.text,
    fontSize: 26,
    fontWeight: '700',
    fontFamily: Fonts.serif,
    fontStyle: 'italic',
  },
  spacer: { flex: 1 },
  horizonBadge: {
    backgroundColor: Cosmic.cardAlt,
    borderRadius: 999,
    paddingVertical: 4,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: Cosmic.border,
  },
  horizonText: {
    color: Cosmic.textDim,
    fontSize: 11,
    fontFamily: Fonts.mono,
  },
  decisionRow: {
    marginTop: 14,
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 12,
  },
  direction: {
    ...TitleShadow.strong,
    fontSize: 30,
    fontWeight: '800',
    letterSpacing: 1,
  },
  conviction: {
    color: Cosmic.textDim,
    fontSize: 14,
    fontFamily: Fonts.mono,
  },
  statGrid: {
    flexDirection: 'row',
    marginTop: 16,
    backgroundColor: Cosmic.cardAlt,
    borderRadius: 12,
    paddingVertical: 12,
  },
  statCell: {
    flex: 1,
    alignItems: 'center',
    gap: 3,
  },
  statLabel: {
    color: Cosmic.textFaint,
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  statValue: {
    color: Cosmic.text,
    fontSize: 18,
    fontWeight: '700',
    fontFamily: Fonts.mono,
  },
  section: {
    marginTop: 16,
    gap: 8,
  },
  sectionTitle: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  driverRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 6,
  },
  driverDot: {
    color: Cosmic.accent,
    fontSize: 13,
    lineHeight: 19,
  },
  driverText: {
    flex: 1,
    color: Cosmic.text,
    fontSize: 14,
    lineHeight: 21,
  },
  sourceChip: {
    backgroundColor: 'rgba(125,158,211,0.14)',
    borderRadius: 6,
    paddingVertical: 2,
    paddingHorizontal: 6,
    alignSelf: 'flex-start',
  },
  sourceChipText: {
    color: Cosmic.macro,
    fontSize: 10,
    fontFamily: Fonts.mono,
  },
  counterBox: {
    marginTop: 16,
    backgroundColor: 'rgba(232,122,122,0.08)',
    borderColor: 'rgba(232,122,122,0.35)',
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 4,
  },
  counterTitle: {
    color: Cosmic.short,
    fontSize: 12,
    fontWeight: '700',
  },
  counterName: {
    color: Cosmic.text,
    fontSize: 14,
    lineHeight: 20,
  },
  counterMitigation: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 19,
  },
  chevron: {
    color: Cosmic.textDim,
    fontSize: 22,
    marginLeft: 4,
    marginTop: -2,
  },
  detailHint: {
    marginTop: 16,
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '600',
    textAlign: 'right',
  },
  disclaimer: {
    marginTop: 10,
    color: Cosmic.textFaint,
    fontSize: 12,
    fontStyle: 'italic',
    textAlign: 'center',
  },
  emptyText: {
    marginTop: 14,
    color: Cosmic.textDim,
    fontSize: 13,
  },
});
