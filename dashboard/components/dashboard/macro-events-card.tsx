/**
 * MacroEventsCard — calendrier macro/géopolitique programmé, fusionné avec la
 * couche éducative « Lecture macro » (mécanisme curé + réaction historique +
 * mouvement live BTC/OR sur l'event qui vient de tomber).
 *
 * Lacune B Phase B1 J+10 (cf. ADR-017). Pattern OSINT pro : dates officielles
 * citant leurs sources (FRED Releases API + Fed Reserve statique pour FOMC),
 * l'humain anticipe ses positions. Zéro signal trading généré, zéro
 * hallucination LLM.
 *
 * Mode compact (Home) : optionnel bandeau live en tête (event ≤48h dans le
 * passé + mouvement RÉEL BTC/OR depuis l'annonce), puis 1 event mis en avant
 * + N suivants. Chaque event a un chevron `▾` (si un mécanisme éducatif est
 * disponible) qui déplie inline : 🔗 mécanisme + actifs + caveat + 📊 réaction
 * historique mesurée BTC/OR.
 *
 * Props éducatives (`readings`, `live`) optionnelles → rétrocompat : la route
 * `/macro` peut continuer à utiliser cette carte sans les passer.
 *
 * Pour retirer la couche éducative et revenir au calendrier seul, cf. memory
 * `macro-reading-educational-layer` (procédure documentée).
 */

import { Link } from 'expo-router';
import { useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import {
  MacroAssetReaction,
  MacroEvent,
  MacroLiveOut,
  MacroReading,
} from '@/src/api/types';
import { useTick } from '@/src/hooks/use-tick';
import { goldClosureNotice } from '@/src/utils/markets';
import { formatLocal, timeAgo, timeUntil } from '@/src/utils/time';

export interface MacroEventsCardProps {
  events: MacroEvent[];
  loading?: boolean;
  error?: string | null;
  /** Cap d'affichage en mode compact (défaut 4 = 1 mis en avant + 3 suivants). */
  displayLimit?: number;
  /** Si true, affiche le bouton "Voir tous". */
  showSeeAll?: boolean;
  /** Fiches éducatives par event_code. Si fourni, active l'expand inline. */
  readings?: MacroReading[];
  /** Lecture live (event ≤48h + mouvement BTC/OR). Si présent et HIGH/MED → bandeau en tête. */
  live?: MacroLiveOut | null;
}

function importanceColor(importance: string): string {
  switch (importance) {
    case 'HIGH':
      return '#c0392b';
    case 'MEDIUM':
      return '#e67e22';
    case 'LOW':
      return '#7f8c8d';
    default:
      return '#7f8c8d';
  }
}

function importanceLabel(importance: string): string {
  return importance.toUpperCase();
}

function eventLabel(code: string, fallback: string): string {
  switch (code) {
    case 'FOMC_MEETING':
      return 'FOMC';
    case 'NFP':
      return 'NFP (emploi US)';
    case 'CPI':
      return 'CPI (inflation US)';
    case 'PPI':
      return 'PPI (prix prod.)';
    case 'GDP':
      return 'GDP (croissance)';
    case 'RETAIL_SALES':
      return 'Retail Sales';
    case 'INDUSTRIAL_PRODUCTION':
      return 'Industrial Prod.';
    case 'INITIAL_CLAIMS':
      return 'Initial Claims';
    default:
      return fallback;
  }
}

function signedPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
}

function moveColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return '#7f8c8d';
  if (v >= 0.5) return '#27ae60';
  if (v <= -0.5) return '#c0392b';
  return '#7f8c8d';
}

/** Format compact d'un MacroAssetReaction (médiane jour + 3j + % haussier). */
function assetSummary(ar: MacroAssetReaction | null): string {
  if (!ar) return '';
  const parts: string[] = [];
  if (ar.same_day) parts.push(`jour ${signedPct(ar.same_day.median)}`);
  if (ar.d3) parts.push(`3j ${signedPct(ar.d3.median)} ↑${Math.round(ar.d3.pct_up)}%`);
  return parts.join('  ·  ');
}

/** Panneau dépliable : mécanisme + actifs + caveat + réaction historique BTC/OR. */
function MechanismPanel({ reading }: { reading: MacroReading }) {
  return (
    <ThemedView style={[styles.panel, { backgroundColor: 'transparent' }]}>
      <ThemedText style={styles.sectionLabel}>🔗 LE MÉCANISME (théorie générale)</ThemedText>
      <ThemedText style={styles.mechanism}>{reading.mechanism}</ThemedText>
      <ThemedText style={styles.assets}>
        Actifs en jeu : {reading.assets_in_play.join(' · ')}
      </ThemedText>
      <ThemedText style={styles.caveat}>⚠ {reading.regime_caveat}</ThemedText>

      <ThemedText style={styles.sectionLabel}>
        📊 MESURÉ PAR TIK (BTC/OR
        {reading.measured_available ? ` · ~${reading.n_dates} cas` : ''})
      </ThemedText>
      {reading.measured_available && (reading.btc || reading.gold) ? (
        <ThemedView style={[styles.measuredBlock, { backgroundColor: 'transparent' }]}>
          <ThemedText style={styles.measuredRow}>
            BTC  {assetSummary(reading.btc) || '—'}
          </ThemedText>
          <ThemedText style={styles.measuredRow}>
            OR   {assetSummary(reading.gold) || '—'}
          </ThemedText>
        </ThemedView>
      ) : (
        <ThemedText style={styles.measuredNa}>
          Pas encore mesuré pour cet event (réaction Tik n/a).
        </ThemedText>
      )}
    </ThemedView>
  );
}

export function MacroEventsCard({
  events,
  loading,
  error,
  displayLimit = 4,
  showSeeAll = true,
  readings,
  live,
}: MacroEventsCardProps) {
  // useTick : « il y a Xmin » / « dans Xmin » restent justes sans re-fetch (Bug B).
  useTick(60_000);

  const scheme = useColorScheme() ?? 'light';
  const palette = Colors[scheme];

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  // Lookup O(1) reading par event_code.
  const readingByCode = useMemo(() => {
    const map = new Map<string, MacroReading>();
    (readings ?? []).forEach((r) => map.set(r.event_code, r));
    return map;
  }, [readings]);

  const visible = events.slice(0, displayLimit);
  const featured = visible[0];
  const followUps = visible.slice(1);

  // Notice fermeture marché de l'or (week-end / jour férié US).
  const goldNotice = goldClosureNotice(new Date());

  // Bandeau live : event HIGH/MEDIUM qui vient de tomber (≤48h backend).
  const liveRecent = live?.recent_event;
  const showLive =
    !!liveRecent && (liveRecent.importance === 'HIGH' || liveRecent.importance === 'MEDIUM');
  // Clé d'expand pour le live (préfixe pour éviter collision avec un event futur du même code).
  const liveKey = liveRecent ? `live:${liveRecent.event_code}:${liveRecent.scheduled_for}` : '';
  const liveExpanded = showLive && expanded.has(liveKey);
  const liveReading = liveRecent ? readingByCode.get(liveRecent.event_code) : undefined;

  return (
    <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
      <ThemedView style={[styles.header, { backgroundColor: 'transparent' }]}>
        <ThemedText type="defaultSemiBold">Calendrier macro</ThemedText>
        <ThemedText style={styles.periodLabel}>
          {showLive ? 'live · 7 j à venir' : '7 j à venir'}
        </ThemedText>
      </ThemedView>

      {goldNotice ? (
        <ThemedView style={styles.goldClosureNotice}>
          <ThemedText style={styles.goldClosureText}>🌙 {goldNotice.label}</ThemedText>
        </ThemedView>
      ) : null}

      {/* Bandeau LIVE en tête : event qui vient de tomber + mouvement réel BTC/OR. */}
      {showLive && liveRecent ? (
        <Pressable
          onPress={() => (liveReading ? toggle(liveKey) : undefined)}
          disabled={!liveReading}
          accessibilityRole={liveReading ? 'button' : undefined}
          style={({ pressed }) => [
            styles.liveBanner,
            {
              borderColor: importanceColor(liveRecent.importance),
              opacity: pressed && liveReading ? 0.7 : 1,
            },
          ]}>
          <ThemedView style={[styles.liveTopRow, { backgroundColor: 'transparent' }]}>
            <ThemedText
              style={[styles.liveStatus, { color: importanceColor(liveRecent.importance) }]}>
              ● IL Y A {timeAgo(liveRecent.scheduled_for)}
            </ThemedText>
            <ThemedView
              style={[
                styles.importanceBadge,
                { backgroundColor: importanceColor(liveRecent.importance) },
              ]}>
              <ThemedText style={styles.importanceLabel}>
                {importanceLabel(liveRecent.importance)}
              </ThemedText>
            </ThemedView>
            {liveReading ? (
              <ThemedText style={styles.chevron}>{liveExpanded ? '▴' : '▾'}</ThemedText>
            ) : null}
          </ThemedView>
          <ThemedText style={styles.featuredEventLabel}>
            {eventLabel(liveRecent.event_code, liveRecent.event_name)}
          </ThemedText>
          <ThemedView style={[styles.liveMovesRow, { backgroundColor: 'transparent' }]}>
            <ThemedText style={styles.moveLabel}>BTC</ThemedText>
            <ThemedText style={[styles.moveValue, { color: moveColor(liveRecent.btc_move_pct) }]}>
              {signedPct(liveRecent.btc_move_pct)}
            </ThemedText>
            <ThemedText style={[styles.moveLabel, { marginLeft: 16 }]}>OR</ThemedText>
            <ThemedText style={[styles.moveValue, { color: moveColor(liveRecent.gold_move_pct) }]}>
              {signedPct(liveRecent.gold_move_pct)}
            </ThemedText>
          </ThemedView>
          <ThemedText style={styles.liveCaveat}>
            Mouvement BRUT depuis l&apos;annonce · pas isolé à la surprise
          </ThemedText>
          {liveExpanded && liveReading ? <MechanismPanel reading={liveReading} /> : null}
        </Pressable>
      ) : null}

      {error ? (
        <ThemedText style={styles.errorText}>Indisponible : {error}</ThemedText>
      ) : loading && events.length === 0 ? (
        <ThemedView style={[styles.loading, { backgroundColor: 'transparent' }]}>
          <ActivityIndicator size="small" />
        </ThemedView>
      ) : !featured ? (
        <ThemedText style={styles.emptyLabel}>
          Aucun event macro programmé sur cette fenêtre.
        </ThemedText>
      ) : (
        <>
          {/* Featured : prochain event + chevron expand inline. */}
          {(() => {
            const reading = readingByCode.get(featured.event_code);
            const key = `evt:${featured.id}`;
            const isExpanded = reading && expanded.has(key);
            return (
              <Pressable
                onPress={() => (reading ? toggle(key) : undefined)}
                disabled={!reading}
                accessibilityRole={reading ? 'button' : undefined}
                accessibilityLabel={
                  reading
                    ? `${isExpanded ? 'Replier' : 'Déplier'} le mécanisme de ${eventLabel(featured.event_code, featured.event_name)}`
                    : undefined
                }
                style={({ pressed }) => [
                  styles.featured,
                  {
                    borderColor: importanceColor(featured.importance),
                    opacity: pressed && reading ? 0.7 : 1,
                  },
                ]}>
                <ThemedView style={[styles.featuredTopRow, { backgroundColor: 'transparent' }]}>
                  <ThemedView
                    style={[
                      styles.importanceBadge,
                      { backgroundColor: importanceColor(featured.importance) },
                    ]}>
                    <ThemedText style={styles.importanceLabel}>
                      {importanceLabel(featured.importance)}
                    </ThemedText>
                  </ThemedView>
                  <ThemedView style={[styles.featuredRightCol, { backgroundColor: 'transparent' }]}>
                    <ThemedText style={styles.featuredCountdown}>
                      {timeUntil(featured.scheduled_for)}
                    </ThemedText>
                    {reading ? (
                      <ThemedText style={styles.chevron}>{isExpanded ? '▴' : '▾'}</ThemedText>
                    ) : null}
                  </ThemedView>
                </ThemedView>
                <ThemedText style={styles.featuredEventLabel}>
                  {eventLabel(featured.event_code, featured.event_name)}
                </ThemedText>
                <ThemedText style={styles.metaLabel}>
                  {formatLocal(featured.scheduled_for)} · {featured.assets_impacted.join(', ')}
                </ThemedText>
                {isExpanded && reading ? <MechanismPanel reading={reading} /> : null}
              </Pressable>
            );
          })()}

          {/* Liste compacte des events suivants — chevron expand inline. */}
          {followUps.length > 0 ? (
            <ThemedView style={[styles.followUps, { backgroundColor: 'transparent' }]}>
              {followUps.map((ev) => {
                const reading = readingByCode.get(ev.event_code);
                const key = `evt:${ev.id}`;
                const isExpanded = reading && expanded.has(key);
                return (
                  <Pressable
                    key={ev.id}
                    onPress={() => (reading ? toggle(key) : undefined)}
                    disabled={!reading}
                    accessibilityRole={reading ? 'button' : undefined}
                    style={({ pressed }) => [
                      styles.followUpWrap,
                      { borderBottomColor: palette.icon, opacity: pressed && reading ? 0.7 : 1 },
                    ]}>
                    <ThemedView style={[styles.followUpRow, { backgroundColor: 'transparent' }]}>
                      <ThemedView
                        style={[
                          styles.importanceDot,
                          { backgroundColor: importanceColor(ev.importance) },
                        ]}
                      />
                      <ThemedText style={styles.followUpLabel} numberOfLines={1}>
                        {eventLabel(ev.event_code, ev.event_name)}
                      </ThemedText>
                      <ThemedText style={styles.metaLabel}>
                        {timeUntil(ev.scheduled_for)}
                      </ThemedText>
                      {reading ? (
                        <ThemedText style={[styles.chevron, { fontSize: 14 }]}>
                          {isExpanded ? '▴' : '▾'}
                        </ThemedText>
                      ) : null}
                    </ThemedView>
                    {isExpanded && reading ? <MechanismPanel reading={reading} /> : null}
                  </Pressable>
                );
              })}
            </ThemedView>
          ) : null}
        </>
      )}

      {showSeeAll && events.length > 0 ? (
        <Link href="/macro" asChild>
          <Pressable
            style={({ pressed }) => [
              styles.seeAll,
              { borderColor: palette.icon, opacity: pressed ? 0.7 : 1 },
            ]}>
            <ThemedText style={styles.seeAllLabel}>Voir tout le calendrier</ThemedText>
          </Pressable>
        </Link>
      ) : null}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 12, padding: 16, gap: 12 },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 4,
  },
  periodLabel: { fontSize: 12, opacity: 0.6 },
  goldClosureNotice: {
    backgroundColor: 'rgba(52, 73, 94, 0.12)',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  goldClosureText: { fontSize: 12, fontWeight: '600', opacity: 0.85 },
  loading: { alignItems: 'center', paddingVertical: 16 },
  emptyLabel: { opacity: 0.6, paddingVertical: 8 },
  errorText: { color: '#c0392b', fontSize: 13 },

  // Bandeau live (event passé ≤48h)
  liveBanner: { borderLeftWidth: 4, paddingLeft: 12, paddingVertical: 8, gap: 4 },
  liveTopRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  liveStatus: { fontSize: 12, fontWeight: '700', letterSpacing: 0.4, flex: 1 },
  liveMovesRow: { flexDirection: 'row', alignItems: 'baseline', gap: 6, marginTop: 4 },
  moveLabel: { fontSize: 11, opacity: 0.6, fontWeight: '700', letterSpacing: 0.4 },
  moveValue: { fontSize: 16, fontWeight: '700', fontVariant: ['tabular-nums'] },
  liveCaveat: { fontSize: 10, opacity: 0.55, fontStyle: 'italic', marginTop: 2 },

  // Featured (next event)
  featured: { borderLeftWidth: 4, paddingLeft: 12, paddingVertical: 6, gap: 4 },
  featuredTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  featuredEventLabel: { fontSize: 16, fontWeight: '700' },
  featuredCountdown: { fontSize: 13, fontWeight: '600', opacity: 0.85 },
  featuredRightCol: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  chevron: { fontSize: 16, fontWeight: '700', opacity: 0.55 },
  importanceBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 3 },
  importanceLabel: { color: '#ffffff', fontSize: 10, fontWeight: '700', letterSpacing: 0.4 },
  metaLabel: { fontSize: 11, opacity: 0.65 },

  // Liste compacte (followUps)
  followUps: { gap: 0 },
  followUpWrap: { borderBottomWidth: StyleSheet.hairlineWidth, paddingVertical: 4 },
  followUpRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 4 },
  importanceDot: { width: 8, height: 8, borderRadius: 4 },
  followUpLabel: { flex: 1, fontSize: 14 },

  // Panneau mécanisme déplié
  panel: { marginTop: 8, gap: 4, paddingTop: 8, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: 'rgba(127,127,127,0.3)' },
  sectionLabel: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.4,
    opacity: 0.7,
    marginTop: 6,
  },
  mechanism: { fontSize: 13, lineHeight: 19 },
  assets: { fontSize: 12, opacity: 0.8, fontWeight: '600' },
  caveat: { fontSize: 11, opacity: 0.65, fontStyle: 'italic', lineHeight: 15 },
  measuredBlock: { gap: 2 },
  measuredRow: { fontSize: 13, fontVariant: ['tabular-nums'] },
  measuredNa: { fontSize: 12, opacity: 0.6, fontStyle: 'italic' },

  seeAll: {
    marginTop: 4,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: 'center',
  },
  seeAllLabel: { fontSize: 13, fontWeight: '600' },
});
