/**
 * Onglet « Signals » cosmique (refonte γ — promu en vrai onglet au bout 5).
 *
 * Était l'écran d'aperçu `app/cosmique.tsx` ; déplacé ici comme onglet Signals
 * principal (le teaser et l'ancien onglet thémé ont été retirés).
 *
 * Port cosmique de l'ancien onglet Signals (que la trader appréciait) :
 *   - filtres en haut : actif (Tous/BTC/GOLD) · horizon (Flash/Swing/Macro) ·
 *     temporalité (24h/5j/30j)
 *   - statut de connexion live
 *   - pastille « Court terme BTC » (stabilité flash) — BTC only (pas de flash GOLD)
 *   - pastille « GOLD swing » (stabilité directionnelle swing) — l'équivalent honnête
 *   - liste des signaux (lignes cosmiques) → tap = page détail (drill-down)
 *   - % expliqués via le ⓘ (glossaire in-app)
 *
 * Pas de cartes BTC/GOLD résumées en haut (doublon avec la liste, retiré sur
 * retour trader). La carte « riche » (drivers + contre-scénario) ira en haut de
 * la page détail (bout 2). Données 100 % réelles.
 */

import { useRouter } from 'expo-router';
import { useCallback, useMemo, useState, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
  type ListRenderItem,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { CosmicSignalRow } from '@/components/cosmic/cosmic-signal-row';
import { InfoTooltip } from '@/components/ui/info-tooltip';
import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import type { MacroRegime, Signal } from '@/src/api/types';
import { computeFlashStability } from '@/src/flash/stability';
import { useMacroRegime } from '@/src/hooks/useMacroRegime';
import { useSignalStream } from '@/src/hooks/useSignalStream';
import { useTick } from '@/src/hooks/use-tick';
import { computeDirectionStability } from '@/src/signals/stability';
import { parseUtcIso } from '@/src/utils/time';

const ENTITY_FILTERS: { label: string; value: string | undefined }[] = [
  { label: 'Tous', value: undefined },
  { label: 'BTC', value: 'BTC' },
  { label: 'GOLD', value: 'GOLD' },
];

const HORIZON_FILTERS: { label: string; value: string | undefined }[] = [
  { label: 'Tous', value: undefined },
  { label: 'Flash', value: 'flash' },
  { label: 'Swing', value: 'swing' },
  { label: 'Macro', value: 'macro' },
  // « Micro » = couche ML btc-research-lab (fusion macro+micro, ADR-033). Signaux
  // en SHADOW (circuit_breaker_status='degraded'). Vide tant que le conteneur
  // micro n'est pas activé sur le VPS.
  { label: 'Micro', value: 'micro' },
];

const DURATION_FILTERS: { label: string; sinceHours: number | undefined; preloadLimit: number }[] = [
  { label: '24h', sinceHours: undefined, preloadLimit: 100 },
  { label: '5j', sinceHours: 120, preloadLimit: 500 },
  { label: '30j', sinceHours: 720, preloadLimit: 1000 },
];

function connectionLabel(state: string): string {
  switch (state) {
    case 'connected':
      return 'Live';
    case 'connecting':
      return 'Connexion…';
    case 'reconnecting':
      return 'Reconnexion…';
    case 'auth_error':
      return 'Auth refusée';
    case 'stopped':
      return 'Arrêté';
    default:
      return 'Inactif';
  }
}

function connectionColor(state: string): string {
  switch (state) {
    case 'connected':
      return Cosmic.long;
    case 'connecting':
    case 'reconnecting':
      return Cosmic.neutral;
    case 'auth_error':
      return Cosmic.short;
    default:
      return Cosmic.textFaint;
  }
}

/** Libellé + couleur compacts pour le bandeau contexte macro (haut de Signals). */
function macroBannerInfo(regime: MacroRegime | null): { text: string; color: string } {
  const r = regime?.global_liquidity?.regime ?? regime?.net_liquidity?.regime ?? null;
  if (r === 'expansion') return { text: 'liquidité mondiale en expansion', color: Cosmic.long };
  if (r === 'contraction') return { text: 'liquidité mondiale en contraction', color: Cosmic.neutral };
  if (r === 'neutral') return { text: 'liquidité mondiale stable', color: Cosmic.textDim };
  return { text: 'voir le contexte', color: Cosmic.textDim };
}

// --- Libellés du détail de stabilité (carnet d'ordres / flux agressif) ---
const BIAS_LABEL: Record<string, string> = {
  bull: 'haussier',
  bear: 'baissier',
  neutral: 'neutre',
  unknown: '—',
};
function biasColor(b: string): string {
  if (b === 'bull') return Cosmic.long;
  if (b === 'bear') return Cosmic.short;
  return Cosmic.textDim;
}
const AGREEMENT_TEXT: Record<string, { label: string; color: string }> = {
  agree: { label: "✓ les 2 sources s'accordent", color: Cosmic.long },
  conflict: { label: '✗ elles se contredisent — signal peu fiable', color: Cosmic.short },
  partial: { label: '~ accord partiel (une source neutre)', color: Cosmic.neutral },
  unknown: { label: 'croisement indisponible', color: Cosmic.textFaint },
};
function dirLabel(d: string): string {
  return d === 'long' ? 'LONG' : d === 'short' ? 'SHORT' : 'NEUTRE';
}
function flashVerdict(state: string, flips: number, win: number, held: number | null): string {
  if (state === 'choppy') return `⚠ INSTABLE — ${flips} bascules long↔short en ${win} min · reste à l'écart`;
  if (state === 'stable')
    return held != null ? `✓ STABLE — direction tenue depuis ${held} min` : '✓ STABLE — direction tenue';
  if (state === 'indecisive') return "~ INDÉCIS — attends une confirmation avant d'agir";
  return 'Pas assez de signaux flash récents';
}

interface Pastille {
  icon: string;
  color: string;
  label: string;
  hint: string;
}

export default function SignalsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const macro = useMacroRegime();
  const macroBanner = macroBannerInfo(macro.regime);

  // Pastille de stabilité dépliée (carnet d'ordres / flux agressif au tap).
  const [openStab, setOpenStab] = useState<null | 'btc' | 'gold'>(null);

  const [entity, setEntity] = useState<string | undefined>(undefined);
  const [horizon, setHorizon] = useState<string | undefined>(undefined);
  const [durationIdx, setDurationIdx] = useState<number>(0);
  const duration = DURATION_FILTERS[durationIdx];

  const { signals, connectionState, error, preloadLoading, preloadError, refresh } = useSignalStream({
    entity,
    horizon,
    sinceHours: duration.sinceHours,
    preloadLimit: duration.preloadLimit,
    maxSignals: duration.preloadLimit,
  });

  const [refreshing, setRefreshing] = useState(false);
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await refresh();
    } finally {
      setRefreshing(false);
    }
  }, [refresh]);

  const tick = useTick();

  // Pastille BTC : stabilité flash (haché ↔ calme). BTC only (pas de flash GOLD).
  const flashStability = useMemo(
    () => computeFlashStability(signals, { entityId: 'BTC' }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signals, tick],
  );
  const flashChoppy = flashStability.state === 'choppy';
  const flashRecentCutoffMs = flashStability.windowMinutes * 60_000;
  const isRecentFlashBtc = useCallback(
    (s: Signal) =>
      s.horizon === 'flash' &&
      s.entity_id === 'BTC' &&
      Date.now() - parseUtcIso(s.timestamp).getTime() <= flashRecentCutoffMs,
    [flashRecentCutoffMs],
  );

  // Pastille GOLD : stabilité directionnelle swing (équivalent honnête, GOLD n'a
  // pas de flash). Fenêtre 48h.
  const goldStability = useMemo(
    () => computeDirectionStability(signals, { entityId: 'GOLD', horizon: 'swing', windowHours: 48 }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signals, tick],
  );

  const openChoppyExplain = useCallback(() => {
    Alert.alert(
      'Court terme indécis (flash BTC)',
      'Le flash a changé plusieurs fois de direction (long↔short) sur les ~45 dernières ' +
        'min. Le très court terme est haché : la direction sert au timing, pas à suivre telle quelle.',
      [{ text: 'OK', style: 'default' }],
    );
  }, []);

  const showFlashBanner = entity === undefined || entity === 'BTC';
  const flashPastille: Pastille = useMemo(() => {
    if (flashStability.state === 'choppy') {
      return { icon: '🔀', color: '#a79bff', label: 'Court terme BTC : haché', hint: 'la direction flip souvent — mauvais moment pour du court terme' };
    }
    if (flashStability.state === 'no_data') {
      return { icon: '•', color: Cosmic.textDim, label: 'Court terme BTC : pas assez de données', hint: 'peu de signaux flash récents' };
    }
    return { icon: '✓', color: Cosmic.long, label: 'Court terme BTC : calme', hint: 'direction du court terme lisible (~45 min)' };
  }, [flashStability.state]);

  const showGoldBanner = entity === undefined || entity === 'GOLD';
  const goldPastille: Pastille = useMemo(() => {
    if (goldStability.state === 'stable') {
      return { icon: '✓', color: Cosmic.long, label: 'GOLD swing : direction stable', hint: 'pas de bascule sur 48 h' };
    }
    if (goldStability.state === 'hesitant') {
      return { icon: '🔀', color: Cosmic.neutral, label: 'GOLD swing : hésitante', hint: 'la direction a basculé récemment' };
    }
    return { icon: '•', color: Cosmic.textDim, label: 'GOLD swing : pas assez de données', hint: 'peu de signaux swing GOLD récents' };
  }, [goldStability.state]);

  const renderItem: ListRenderItem<Signal> = useCallback(
    ({ item }) => (
      <CosmicSignalRow
        signal={item}
        showChoppy={flashChoppy && isRecentFlashBtc(item)}
        onChoppyPress={openChoppyExplain}
      />
    ),
    [flashChoppy, isRecentFlashBtc, openChoppyExplain],
  );

  const filterPill = (label: string, active: boolean, onPress: () => void) => (
    <Pressable
      key={label}
      onPress={onPress}
      style={({ pressed }) => [
        styles.pill,
        {
          backgroundColor: active ? Cosmic.accent : 'transparent',
          borderColor: active ? Cosmic.accent : Cosmic.borderStrong,
          opacity: pressed ? 0.7 : 1,
        },
      ]}>
      <Text style={[styles.pillLabel, { color: active ? Cosmic.bgDeep : Cosmic.textDim }]}>{label}</Text>
    </Pressable>
  );

  const renderPastille = (key: 'btc' | 'gold', p: Pastille, show: boolean, detail: ReactNode) => {
    if (!show) return null;
    const open = openStab === key;
    return (
      <View>
        <Pressable
          onPress={() => setOpenStab(open ? null : key)}
          style={[styles.pastille, { borderColor: p.color + '66' }]}>
          <View style={styles.pastilleTop}>
            <Text style={[styles.pastilleLabel, { color: p.color }]}>
              {p.icon} {p.label}
            </Text>
            <Text style={styles.pastilleChevron}>{open ? '⌄' : '›'}</Text>
          </View>
          <Text style={styles.pastilleHint}>{p.hint} · touche pour le détail</Text>
        </Pressable>
        {open ? detail : null}
      </View>
    );
  };

  // Détail dépliable BTC : verdict + croisement carnet d'ordres / flux agressif.
  const btcStabDetail = (
    <View style={styles.stabDetail}>
      <Text style={[styles.stabVerdict, { color: flashPastille.color }]}>
        {flashVerdict(
          flashStability.state,
          flashStability.flips,
          flashStability.windowMinutes,
          flashStability.directionHeldMinutes,
        )}
      </Text>
      {flashStability.state !== 'no_data' ? (
        <Text style={styles.stabMeta}>
          Direction actuelle : {dirLabel(flashStability.currentDirection)} · {flashStability.count}{' '}
          signaux / {flashStability.windowMinutes} min
        </Text>
      ) : null}
      {flashStability.cross ? (
        <View style={styles.crossBox}>
          <Text style={styles.crossTitle}>Croisement des 2 sources · dernier signal</Text>
          <View style={styles.crossRow}>
            <Text style={styles.crossName}>Carnet d&apos;ordres</Text>
            <Text
              style={[styles.crossBias, { color: biasColor(flashStability.cross.orderbook.bias) }]}
              numberOfLines={1}>
              {BIAS_LABEL[flashStability.cross.orderbook.bias] ?? '—'}
              {flashStability.cross.orderbook.detail
                ? ` · ${flashStability.cross.orderbook.detail}`
                : ''}
            </Text>
          </View>
          <View style={styles.crossRow}>
            <Text style={styles.crossName}>Flux agressif</Text>
            <Text
              style={[styles.crossBias, { color: biasColor(flashStability.cross.aggression.bias) }]}
              numberOfLines={1}>
              {BIAS_LABEL[flashStability.cross.aggression.bias] ?? '—'}
              {flashStability.cross.aggression.detail
                ? ` · ${flashStability.cross.aggression.detail}`
                : ''}
            </Text>
          </View>
          <Text
            style={[
              styles.crossAgreement,
              { color: AGREEMENT_TEXT[flashStability.cross.agreement].color },
            ]}>
            {AGREEMENT_TEXT[flashStability.cross.agreement].label}
          </Text>
        </View>
      ) : null}
      <Text style={styles.stabFoot}>
        Le flash dérive de 2 sources microstructure (carnet d&apos;ordres + flux agressif) ; il est
        bruité, sans edge prouvé. Idéal : direction stable ET sources d&apos;accord — sinon ne trade
        pas le court terme.
      </Text>
    </View>
  );

  // Détail dépliable GOLD : stabilité swing (pas de microstructure flash sur GOLD).
  const goldStabDetail = (
    <View style={styles.stabDetail}>
      {goldStability.state !== 'no_data' ? (
        <Text style={styles.stabMeta}>
          Direction actuelle : {dirLabel(goldStability.currentDirection)} · {goldStability.flips}{' '}
          bascule(s) sur {goldStability.windowHours} h · {goldStability.count} signaux swing
        </Text>
      ) : null}
      <Text style={styles.stabFoot}>
        GOLD n&apos;a pas de moteur « flash » (Yahoo a 15 min de retard) — donc pas de carnet
        d&apos;ordres ni de flux agressif comme le BTC. On regarde si la direction de ses signaux
        SWING tient (stable) ou bascule long↔short (hésitante) sur 48 h. Pas une garantie de sens
        (aucun edge prouvé).
      </Text>
    </View>
  );

  const ListHeader = (
    <View style={styles.header}>
      <View style={styles.statusRow}>
        <Text style={styles.title}>
          Tik<Text style={styles.brandSub}> · signals</Text>
        </Text>
        <View style={styles.statusInline}>
          <View style={[styles.dot, { backgroundColor: connectionColor(connectionState) }]} />
          <Text style={[styles.statusText, { color: connectionColor(connectionState) }]}>
            {connectionLabel(connectionState)}
          </Text>
        </View>
      </View>

      {/* Bandeau contexte macro compact → page Macro cosmique (bout 3) */}
      <Pressable
        onPress={() => router.push('/macro-cosmique')}
        style={({ pressed }) => [styles.macroBanner, { opacity: pressed ? 0.7 : 1 }]}
        accessibilityRole="button"
        accessibilityLabel="Voir le contexte macro">
        <Text style={styles.macroBannerText} numberOfLines={1}>
          🌐 Macro · <Text style={{ color: macroBanner.color }}>{macroBanner.text}</Text>
        </Text>
        <Text style={styles.macroChevron}>›</Text>
      </Pressable>

      <View style={styles.filterRow}>
        {DURATION_FILTERS.map((d, idx) => filterPill(d.label, durationIdx === idx, () => setDurationIdx(idx)))}
      </View>
      <View style={styles.filterRow}>
        {ENTITY_FILTERS.map((f) => filterPill(f.label, entity === f.value, () => setEntity(f.value)))}
      </View>
      <View style={styles.filterRow}>
        {HORIZON_FILTERS.map((f) => filterPill(f.label, horizon === f.value, () => setHorizon(f.value)))}
      </View>

      {renderPastille('btc', flashPastille, showFlashBanner, btcStabDetail)}
      {renderPastille('gold', goldPastille, showGoldBanner, goldStabDetail)}

      <View style={styles.legendRow}>
        <Text style={styles.legendText}>conv</Text>
        <InfoTooltip entryKey="conviction" />
        <Text style={styles.legendSep}>·</Text>
        <Text style={styles.legendText}>accord</Text>
        <InfoTooltip entryKey="veracity" />
        <Text style={styles.legendSep}>·</Text>
        <Text style={styles.legendText}>horizon</Text>
        <InfoTooltip entryKey="horizon" />
      </View>

      {error || preloadError ? (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error ?? preloadError}</Text>
        </View>
      ) : null}
    </View>
  );

  return (
    <CosmicBackground>
      {preloadLoading && signals.length === 0 ? (
        <View style={[styles.center, { paddingTop: insets.top + 12 }]}>
          {ListHeader}
          <ActivityIndicator size="large" color={Cosmic.accent} />
          <Text style={styles.emptyText}>Chargement des derniers signaux…</Text>
        </View>
      ) : (
        <FlatList
          data={signals}
          extraData={`${tick}-${flashChoppy}-${openStab}`}
          keyExtractor={(item) => item.id}
          renderItem={renderItem}
          ListHeaderComponent={ListHeader}
          ListEmptyComponent={
            <Text style={styles.emptyText}>
              Aucun signal pour l’instant. Le flux est ouvert, les nouveaux signaux apparaîtront ici.
            </Text>
          }
          contentContainerStyle={[styles.listContent, { paddingTop: insets.top + 12 }]}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Cosmic.accent} />
          }
        />
      )}
    </CosmicBackground>
  );
}

const styles = StyleSheet.create({
  listContent: {
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 40,
  },
  center: {
    flex: 1,
    paddingHorizontal: 16,
    paddingTop: 12,
    gap: 16,
  },
  header: {
    gap: 10,
    marginBottom: 8,
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    ...TitleShadow.glow,
    fontFamily: serifTitleFamily,
    color: Cosmic.accent,
    fontSize: 26,
    fontStyle: 'italic',
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  brandSub: {
    color: Cosmic.text,
    fontWeight: '400',
  },
  statusInline: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
  },
  dot: {
    width: 9,
    height: 9,
    borderRadius: 5,
  },
  macroBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderWidth: 1,
    borderColor: Cosmic.borderStrong,
    borderRadius: 10,
    paddingHorizontal: 11,
    paddingVertical: 8,
    backgroundColor: Cosmic.card,
  },
  macroBannerText: {
    flex: 1,
    color: Cosmic.textDim,
    fontSize: 13,
    fontWeight: '600',
  },
  macroChevron: {
    color: Cosmic.textDim,
    fontSize: 18,
  },
  filterRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  pill: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 13,
    paddingVertical: 6,
  },
  pillLabel: {
    fontSize: 13,
    fontWeight: '700',
  },
  pastille: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 11,
    paddingVertical: 8,
    backgroundColor: Cosmic.card,
    gap: 2,
  },
  pastilleTop: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  pastilleLabel: {
    fontSize: 13,
    fontWeight: '700',
    flex: 1,
  },
  pastilleChevron: {
    color: Cosmic.textDim,
    fontSize: 16,
    marginLeft: 6,
  },
  pastilleHint: {
    color: Cosmic.textFaint,
    fontSize: 11,
  },
  stabDetail: {
    marginTop: 6,
    borderWidth: 1,
    borderColor: Cosmic.border,
    borderRadius: 10,
    padding: 11,
    backgroundColor: Cosmic.cardAlt,
    gap: 6,
  },
  stabVerdict: {
    fontSize: 13,
    fontWeight: '700',
  },
  stabMeta: {
    color: Cosmic.textDim,
    fontSize: 12,
  },
  crossBox: {
    marginTop: 2,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: Cosmic.border,
    gap: 4,
  },
  crossTitle: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontWeight: '600',
  },
  crossRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  crossName: {
    color: Cosmic.text,
    fontSize: 13,
  },
  crossBias: {
    fontSize: 13,
    fontWeight: '600',
    flexShrink: 1,
    textAlign: 'right',
  },
  crossAgreement: {
    fontSize: 13,
    fontWeight: '600',
    marginTop: 2,
  },
  stabFoot: {
    color: Cosmic.textFaint,
    fontSize: 11,
    lineHeight: 16,
    fontStyle: 'italic',
  },
  legendRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    marginTop: 2,
  },
  legendText: {
    color: Cosmic.textDim,
    fontSize: 12,
  },
  legendSep: {
    color: Cosmic.textFaint,
    fontSize: 12,
  },
  errorBox: {
    borderWidth: 1,
    borderColor: Cosmic.short + '88',
    borderRadius: 10,
    padding: 10,
    backgroundColor: 'rgba(232,122,122,0.08)',
  },
  errorText: {
    color: Cosmic.short,
    fontSize: 13,
  },
  emptyText: {
    color: Cosmic.textDim,
    fontSize: 13,
    textAlign: 'center',
    paddingHorizontal: 16,
    marginTop: 12,
  },
});
