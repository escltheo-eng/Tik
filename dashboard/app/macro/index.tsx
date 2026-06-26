/**
 * Calendrier macro cosmique (refonte γ, bout 6 — maquette gamma 03).
 *
 * Events macro/banques centrales programmés (FRED + calendriers BC), groupés par
 * jour avec tags colorés, façon « agenda » de la maquette. Données réelles via
 * `useUpcomingMacroEvents` ; filtre par importance conservé. Remplace l'ancienne
 * vue thémée (qui réutilisait juste MacroEventsCard).
 */

import { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { UnavailableState } from '@/components/cosmic/cosmic-unavailable-state';
import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import type { MacroEvent } from '@/src/api/types';
import { useTick } from '@/src/hooks/use-tick';
import { useUpcomingMacroEvents } from '@/src/hooks/useUpcomingMacroEvents';
import { parseUtcIso } from '@/src/utils/time';

type Importance = 'HIGH' | 'MEDIUM' | 'LOW';
const ALL_LEVELS: readonly Importance[] = ['HIGH', 'MEDIUM', 'LOW'] as const;
const LEVEL_LABEL: Record<Importance, string> = { HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low' };

const MOIS = ['janv', 'févr', 'mars', 'avr', 'mai', 'juin', 'juil', 'août', 'sept', 'oct', 'nov', 'déc'];

function pad(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function dayLabel(d: Date): string {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(d);
  target.setHours(0, 0, 0, 0);
  const diff = Math.round((target.getTime() - today.getTime()) / 86_400_000);
  const base = `${d.getDate()} ${MOIS[d.getMonth()]}`;
  if (diff === 0) return `Aujourd'hui · ${base}`;
  if (diff === 1) return `Demain · ${base}`;
  return base;
}

/** Catégorie + couleur d'un event (banque centrale vs macro générale). */
function category(ev: MacroEvent): { label: string; color: string } {
  const c = (ev.event_code || '').toUpperCase();
  if (c.includes('FOMC') || c.includes('FED')) return { label: 'FED', color: Cosmic.neutral };
  if (c.includes('ECB') || c.includes('BCE')) return { label: 'BCE', color: Cosmic.neutral };
  if (c.includes('BOJ')) return { label: 'BoJ', color: Cosmic.neutral };
  if (c.includes('BOE')) return { label: 'BoE', color: Cosmic.neutral };
  return { label: 'MACRO', color: Cosmic.macro };
}

function importanceColor(imp: string): string {
  if (imp === 'HIGH') return Cosmic.short;
  if (imp === 'MEDIUM') return Cosmic.neutral;
  return Cosmic.textFaint;
}

export default function MacroEventsScreen() {
  const insets = useSafeAreaInsets();
  const [activeLevels, setActiveLevels] = useState<Set<Importance>>(new Set(ALL_LEVELS));
  const importanceFilter = Array.from(activeLevels);

  const { events, loading, error } = useUpcomingMacroEvents({
    hours: 14 * 24,
    importance: importanceFilter.length === 0 ? undefined : importanceFilter,
    limit: 30,
  });
  useTick();

  const toggleLevel = (level: Importance) => {
    setActiveLevels((prev) => {
      const next = new Set(prev);
      if (next.has(level)) next.delete(level);
      else next.add(level);
      return next;
    });
  };

  // Groupage par jour (events déjà triés ASC par le hook).
  const groups = useMemo(() => {
    const out: { key: string; label: string; events: MacroEvent[] }[] = [];
    const map = new Map<string, { key: string; label: string; events: MacroEvent[] }>();
    for (const ev of events) {
      const d = parseUtcIso(ev.scheduled_for);
      const key = dayKey(d);
      let g = map.get(key);
      if (!g) {
        g = { key, label: dayLabel(d), events: [] };
        map.set(key, g);
        out.push(g);
      }
      g.events.push(ev);
    }
    return out;
  }, [events]);

  const nextHigh = events.find((e) => e.importance === 'HIGH') ?? null;

  return (
    <CosmicBackground>
      <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + 10 }]}>
        {/* Header */}
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.brand}>
              Tik<Text style={styles.brandSub}> · agenda</Text>
            </Text>
            <Text style={styles.brandTag}>{events.length} events · 14 jours</Text>
          </View>
          <View style={styles.headerMeta}>
            <Text style={styles.headerMetaLabel}>Prochain critique</Text>
            <Text style={[styles.headerMetaValue, { color: nextHigh ? Cosmic.short : Cosmic.textFaint }]}>
              {nextHigh ? nextHigh.event_name : '—'}
            </Text>
          </View>
        </View>

        {/* Filtres importance */}
        <View style={styles.filters}>
          {ALL_LEVELS.map((level) => {
            const active = activeLevels.has(level);
            return (
              <Pressable
                key={level}
                onPress={() => toggleLevel(level)}
                style={({ pressed }) => [
                  styles.filterPill,
                  {
                    backgroundColor: active ? Cosmic.accent : 'transparent',
                    borderColor: active ? Cosmic.accent : Cosmic.borderStrong,
                    opacity: pressed ? 0.7 : 1,
                  },
                ]}>
                <Text style={[styles.filterLabel, { color: active ? Cosmic.bgDeep : Cosmic.textDim }]}>
                  {LEVEL_LABEL[level]}
                </Text>
              </Pressable>
            );
          })}
        </View>

        {/* États */}
        {error ? (
          <UnavailableState kind="error" error={error} />
        ) : loading && events.length === 0 ? (
          <UnavailableState kind="loading" message="Chargement de l'agenda…" />
        ) : groups.length === 0 ? (
          <UnavailableState kind="empty" message="Aucun event sur la fenêtre / le filtre choisi." />
        ) : (
          groups.map((g) => (
            <View key={g.key} style={styles.day}>
              <View style={styles.dayLabelRow}>
                <Text style={styles.dayLabel}>{g.label}</Text>
                <Text style={styles.dayMeta}>{g.events.length} event{g.events.length > 1 ? 's' : ''}</Text>
              </View>
              {g.events.map((ev) => {
                const d = parseUtcIso(ev.scheduled_for);
                const cat = category(ev);
                return (
                  <View key={ev.id} style={styles.event}>
                    <Text style={styles.eventTime}>
                      {pad(d.getHours())}:{pad(d.getMinutes())}
                    </Text>
                    <View style={styles.eventContent}>
                      <Text style={styles.eventTitle}>{ev.event_name}</Text>
                      <Text style={styles.eventDetail}>
                        <Text style={{ color: importanceColor(ev.importance) }}>{ev.importance}</Text>
                        {ev.assets_impacted?.length ? ` · ${ev.assets_impacted.join(', ')}` : ''}
                      </Text>
                    </View>
                    <View style={[styles.eventTag, { backgroundColor: cat.color + '26' }]}>
                      <Text style={[styles.eventTagText, { color: cat.color }]}>{cat.label}</Text>
                    </View>
                  </View>
                );
              })}
            </View>
          ))
        )}

        <Text style={styles.footer}>
          Sources : FRED Releases (US gov) + calendriers banques centrales. Discipline ±4h autour des
          events HIGH (Garde-fou 2-bis).
        </Text>
      </ScrollView>
    </CosmicBackground>
  );
}

const styles = StyleSheet.create({
  scroll: { paddingHorizontal: 16, paddingBottom: 40, gap: 12 },
  headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end' },
  brand: {
    ...TitleShadow.glow,
    fontFamily: serifTitleFamily,
    color: Cosmic.accent,
    fontSize: 26,
    fontStyle: 'italic',
    fontWeight: '700',
  },
  brandSub: { color: Cosmic.text, fontWeight: '400' },
  brandTag: {
    color: Cosmic.textFaint,
    fontSize: 9,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    fontFamily: Fonts.mono,
    marginTop: 3,
  },
  headerMeta: { alignItems: 'flex-end', maxWidth: 150 },
  headerMetaLabel: {
    color: Cosmic.textFaint,
    fontSize: 8,
    letterSpacing: 1,
    textTransform: 'uppercase',
    fontFamily: Fonts.mono,
  },
  headerMetaValue: { fontSize: 12, fontWeight: '700', marginTop: 2, textAlign: 'right' },
  filters: { flexDirection: 'row', gap: 8 },
  filterPill: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 6,
  },
  filterLabel: { fontSize: 13, fontWeight: '700' },
  day: { gap: 2, marginTop: 6 },
  dayLabelRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    borderBottomWidth: 1,
    borderBottomColor: Cosmic.border,
    paddingBottom: 8,
    marginBottom: 4,
  },
  dayLabel: {
    fontFamily: serifTitleFamily,
    fontStyle: 'italic',
    color: Cosmic.accent,
    fontSize: 15,
    fontWeight: '600',
  },
  dayMeta: {
    color: Cosmic.textFaint,
    fontSize: 9,
    letterSpacing: 1,
    textTransform: 'uppercase',
    fontFamily: Fonts.mono,
  },
  event: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 10,
  },
  eventTime: {
    color: Cosmic.textDim,
    fontSize: 13,
    fontWeight: '600',
    fontFamily: Fonts.mono,
    width: 46,
  },
  eventContent: { flex: 1, gap: 2 },
  eventTitle: { color: Cosmic.text, fontSize: 14, fontWeight: '600', lineHeight: 18 },
  eventDetail: { color: Cosmic.textFaint, fontSize: 12, fontFamily: Fonts.mono },
  eventTag: {
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  eventTagText: {
    fontSize: 9,
    fontWeight: '800',
    letterSpacing: 0.8,
    fontFamily: Fonts.mono,
  },
  empty: {
    color: Cosmic.textDim,
    fontSize: 14,
    textAlign: 'center',
    paddingVertical: 20,
  },
  footer: {
    color: Cosmic.textFaint,
    fontSize: 11,
    lineHeight: 16,
    fontStyle: 'italic',
    marginTop: 8,
  },
});
