/**
 * Cockpit cosmique (refonte γ, bout 6) — vue unique « Puis-je trader ? ».
 *
 * Landing quotidien : bandeau macro réel + statut de DISCIPLINE (F1) + dernier
 * signal BTC + trades ouverts + prochain event. Le contexte (sources) vit dans
 * l'onglet Sources ; les stats/perf/config dans l'onglet Plus.
 *
 * Honnêteté (Axe #1) : le statut dit « y a-t-il un frein ? », PAS « achète » —
 * aucun edge directionnel prouvé (NO-GO 2026-05-27). Données 100 % réelles.
 */

import { useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { CosmicSignalCard } from '@/components/cosmic/cosmic-signal-card';
import { Cosmic, TitleShadow, directionMeta, serifTitleFamily } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import { getHealth } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { Health, Signal } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';
import { useDashboardKpis } from '@/src/hooks/useDashboardKpis';
import { useMacroRegime } from '@/src/hooks/useMacroRegime';
import { useTick } from '@/src/hooks/use-tick';
import { useTrades } from '@/src/journal/useTrades';
import { useUpcomingMacroEvents } from '@/src/hooks/useUpcomingMacroEvents';
import { formatLocal, parseUtcIso } from '@/src/utils/time';

const HEALTH_REFRESH_INTERVAL_MS = 30_000;
const MACRO_WINDOW_MS = 4 * 3600 * 1000; // ±4h discipline (Garde-fou 2-bis)
const SWING_VERACITY_FLOOR = 0.85; // seuil transitoire Garde-fou 2-bis

interface HealthState {
  status: 'idle' | 'loading' | 'ok' | 'error';
  data: Health | null;
  error: string | null;
}
const INITIAL_HEALTH: HealthState = { status: 'idle', data: null, error: null };

/** Label + couleur d'un régime de liquidité. */
function regimeView(r: string | null | undefined): { label: string; color: string } {
  if (r === 'expansion') return { label: 'Expansion', color: Cosmic.long };
  if (r === 'contraction') return { label: 'Contraction', color: Cosmic.neutral };
  if (r === 'neutral') return { label: 'Stable', color: Cosmic.textDim };
  return { label: '—', color: Cosmic.textFaint };
}

export default function HomeScreen() {
  const { client } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const [healthState, setHealthState] = useState<HealthState>(INITIAL_HEALTH);
  const checkHealth = useCallback(async () => {
    setHealthState((s) => ({ ...s, status: 'loading' }));
    try {
      const data = await getHealth(client);
      setHealthState({ status: 'ok', data, error: null });
    } catch (err) {
      const msg = err instanceof TikError ? err.message : (err as Error).message;
      setHealthState({ status: 'error', data: null, error: msg });
    }
  }, [client]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (!cancelled) await checkHealth();
    })();
    const id = setInterval(() => {
      if (!cancelled) void checkHealth();
    }, HEALTH_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [checkHealth]);

  const kpis = useDashboardKpis();
  const macroEventsState = useUpcomingMacroEvents({ hours: 7 * 24, limit: 8 });
  const macroRegimeState = useMacroRegime();
  const { trades } = useTrades();
  useTick();

  const statusLabel: Record<HealthState['status'], string> = {
    idle: 'Inactif',
    loading: 'Vérification…',
    ok: 'Connecté',
    error: 'Hors ligne',
  };
  const statusColor: Record<HealthState['status'], string> = {
    idle: Cosmic.textFaint,
    loading: Cosmic.textFaint,
    ok: Cosmic.long,
    error: Cosmic.short,
  };

  // --- Données dérivées du cockpit (100 % réelles) ---
  const latestBtc: Signal | null = kpis.lastSignalByEntity['BTC'] ?? null;

  const latestBtcSwing = useMemo(
    () =>
      [...kpis.signals24h]
        .filter((s) => s.entity_id === 'BTC' && s.horizon === 'swing')
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0] ?? null,
    [kpis.signals24h],
  );

  const macroBlockEvent = useMemo(() => {
    const now = Date.now();
    return (
      macroEventsState.events.find(
        (e) =>
          e.importance === 'HIGH' &&
          Math.abs(parseUtcIso(e.scheduled_for).getTime() - now) <= MACRO_WINDOW_MS,
      ) ?? null
    );
  }, [macroEventsState.events]);

  const nextEvent = macroEventsState.events[0] ?? null;
  const openTrades = useMemo(() => trades.filter((t) => t.status === 'open'), [trades]);

  const swingVeracityOk = latestBtcSwing ? latestBtcSwing.veracity >= SWING_VERACITY_FLOOR : false;
  const discipline: { color: string; head: string } = macroBlockEvent
    ? { color: Cosmic.short, head: '🔴 Frein de discipline' }
    : !latestBtcSwing || !swingVeracityOk
      ? { color: Cosmic.neutral, head: '🟠 Prudence' }
      : { color: Cosmic.long, head: '🟢 Aucun frein de discipline' };

  const criteria: { ok: boolean; text: string }[] = [
    macroBlockEvent
      ? { ok: false, text: `Event macro HIGH ±4h (${macroBlockEvent.event_name}) — ne pas entrer, ou sizing ÷2` }
      : { ok: true, text: "Pas d'event macro HIGH dans les ±4h" },
    latestBtcSwing
      ? {
          ok: swingVeracityOk,
          text: `Veracity dernier swing BTC ${(latestBtcSwing.veracity * 100).toFixed(0)}%${swingVeracityOk ? '' : ' < 85 %'}`,
        }
      : { ok: false, text: 'Pas de signal swing BTC récent' },
    { ok: true, text: 'Marché BTC ouvert (24/7)' },
    { ok: true, text: 'Sizing 1 % max — ta vraie protection' },
  ];

  const liq = regimeView(macroRegimeState.regime?.global_liquidity?.regime);
  const recession = macroRegimeState.regime?.indicators?.recession_prob_12m?.value ?? null;
  const realRate = macroRegimeState.regime?.indicators?.real_rate_10y?.value ?? null;

  return (
    <CosmicBackground>
      <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + 10 }]}>
        {/* Header */}
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.brand}>
              Tik<Text style={styles.brandSub}> · cockpit</Text>
            </Text>
            <Text style={styles.brandTag}>Observatoire OSINT</Text>
          </View>
          <View style={styles.headerMeta}>
            <Text style={styles.headerMetaLabel}>État du core</Text>
            <Text style={[styles.headerMetaValue, { color: statusColor[healthState.status] }]}>
              {statusLabel[healthState.status]}
            </Text>
          </View>
        </View>

        {/* Bandeau global macro (réel) → page Macro */}
        <Pressable
          onPress={() => router.push('/macro-cosmique')}
          style={({ pressed }) => [styles.globalStrip, { opacity: pressed ? 0.8 : 1 }]}>
          <View style={styles.globalItem}>
            <Text style={styles.globalLabel}>Liquidité</Text>
            <Text style={[styles.globalValue, { color: liq.color }]}>{liq.label}</Text>
          </View>
          <View style={[styles.globalItem, styles.globalItemMid]}>
            <Text style={styles.globalLabel}>Récession 12m</Text>
            <Text
              style={[
                styles.globalValue,
                { color: recession != null && recession >= 0.5 ? Cosmic.neutral : Cosmic.text },
              ]}>
              {recession != null ? `${(recession * 100).toFixed(0)}%` : '—'}
            </Text>
          </View>
          <View style={styles.globalItem}>
            <Text style={styles.globalLabel}>Taux réel 10Y</Text>
            <Text style={styles.globalValue}>{realRate != null ? `${realRate.toFixed(2)}%` : '—'}</Text>
          </View>
        </Pressable>

        {/* Statut de discipline (F1) */}
        <View style={[styles.disciplineCard, { borderColor: discipline.color + '88' }]}>
          <Text style={[styles.disciplineHead, { color: discipline.color }]}>{discipline.head}</Text>
          <Text style={styles.disciplineSub}>
            « Puis-je trader ? » = freins de discipline, PAS un ordre d&apos;achat (aucun edge prouvé).
          </Text>
          {criteria.map((c, i) => (
            <View key={i} style={styles.critRow}>
              <Text style={[styles.critIcon, { color: c.ok ? Cosmic.long : Cosmic.neutral }]}>
                {c.ok ? '✓' : '⚠'}
              </Text>
              <Text style={styles.critText}>{c.text}</Text>
            </View>
          ))}
        </View>

        {/* Dernier signal BTC (priorité) */}
        <Text style={styles.sectionLabel}>Dernier signal BTC</Text>
        <CosmicSignalCard entityId="BTC" signal={latestBtc} loading={kpis.loading} />

        {/* Trades ouverts → Carnet */}
        {openTrades.length > 0 ? (
          <Pressable
            onPress={() => router.push('/journal')}
            style={({ pressed }) => [styles.openTrades, { opacity: pressed ? 0.8 : 1 }]}>
            <Text style={styles.sectionLabel}>Mes trades ouverts ({openTrades.length})</Text>
            {openTrades.slice(0, 3).map((t) => {
              const dir = directionMeta(t.direction);
              return (
                <View key={t.id} style={styles.openTradeRow}>
                  <Text style={styles.openTradeEntity}>{t.entity_id}</Text>
                  <Text style={[styles.openTradeDir, { color: dir.color }]}>{dir.label}</Text>
                  <Text style={styles.openTradeMeta}>{t.size_lots} lot · @ {t.entry_price}</Text>
                </View>
              );
            })}
            <Text style={styles.openTradesHint}>Ouvrir le Carnet ›</Text>
          </Pressable>
        ) : null}

        {/* Prochain event macro */}
        {nextEvent ? (
          <Pressable
            onPress={() => router.push('/macro')}
            style={({ pressed }) => [styles.nextEvent, { opacity: pressed ? 0.8 : 1 }]}>
            <Text style={styles.nextEventLabel}>📅 Prochain event</Text>
            <Text style={styles.nextEventText} numberOfLines={1}>
              {nextEvent.event_name} · {formatLocal(nextEvent.scheduled_for)}
            </Text>
            <Text style={styles.nextEventChevron}>›</Text>
          </Pressable>
        ) : null}
      </ScrollView>
    </CosmicBackground>
  );
}

const styles = StyleSheet.create({
  scroll: {
    paddingHorizontal: 16,
    paddingBottom: 40,
    gap: 12,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-end',
  },
  brand: {
    ...TitleShadow.glow,
    fontFamily: serifTitleFamily,
    color: Cosmic.accent,
    fontSize: 26,
    fontStyle: 'italic',
    fontWeight: '700',
  },
  brandSub: {
    color: Cosmic.text,
    fontWeight: '400',
  },
  brandTag: {
    color: Cosmic.textFaint,
    fontSize: 9,
    letterSpacing: 1.5,
    textTransform: 'uppercase',
    fontFamily: Fonts.mono,
    marginTop: 3,
  },
  headerMeta: {
    alignItems: 'flex-end',
  },
  headerMetaLabel: {
    color: Cosmic.textFaint,
    fontSize: 8,
    letterSpacing: 1,
    textTransform: 'uppercase',
    fontFamily: Fonts.mono,
  },
  headerMetaValue: {
    fontSize: 12,
    fontWeight: '700',
    marginTop: 2,
  },
  globalStrip: {
    flexDirection: 'row',
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 14,
    paddingVertical: 12,
  },
  globalItem: {
    flex: 1,
    alignItems: 'center',
    gap: 5,
  },
  globalItemMid: {
    borderLeftWidth: 1,
    borderRightWidth: 1,
    borderColor: Cosmic.border,
  },
  globalLabel: {
    color: Cosmic.textFaint,
    fontSize: 8,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    fontFamily: Fonts.mono,
  },
  globalValue: {
    color: Cosmic.text,
    fontSize: 16,
    fontWeight: '700',
    fontFamily: serifTitleFamily,
    fontStyle: 'italic',
  },
  disciplineCard: {
    backgroundColor: Cosmic.card,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
    gap: 6,
  },
  disciplineHead: {
    fontSize: 15,
    fontWeight: '800',
  },
  disciplineSub: {
    color: Cosmic.textFaint,
    fontSize: 12,
    fontStyle: 'italic',
    marginBottom: 2,
  },
  critRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
  },
  critIcon: {
    fontSize: 13,
    fontWeight: '800',
    width: 14,
  },
  critText: {
    flex: 1,
    color: Cosmic.textDim,
    fontSize: 14,
    lineHeight: 20,
  },
  sectionLabel: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginTop: 4,
  },
  openTrades: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
    gap: 6,
  },
  openTradeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  openTradeEntity: {
    color: Cosmic.text,
    fontSize: 14,
    fontWeight: '700',
    width: 44,
  },
  openTradeDir: {
    fontSize: 12,
    fontWeight: '800',
    width: 64,
  },
  openTradeMeta: {
    color: Cosmic.textDim,
    fontSize: 13,
    fontFamily: Fonts.mono,
  },
  openTradesHint: {
    color: Cosmic.accent,
    fontSize: 12,
    fontWeight: '600',
    textAlign: 'right',
    marginTop: 2,
  },
  nextEvent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 11,
    paddingHorizontal: 12,
  },
  nextEventLabel: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontWeight: '600',
  },
  nextEventText: {
    flex: 1,
    color: Cosmic.text,
    fontSize: 13,
  },
  nextEventChevron: {
    color: Cosmic.textDim,
    fontSize: 18,
  },
});
