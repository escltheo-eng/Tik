import { useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { AntiFakeNewsBadge } from '@/components/dashboard/anti-fake-news-badge';
import { NearMacroBadge } from '@/components/dashboard/near-macro-badge';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Collapsible } from '@/components/ui/collapsible';
import { InfoTooltip } from '@/components/ui/info-tooltip';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { getSignal, getSignalTrackRecord } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import { Signal, SignalTrackRecord, TrackRecordRow } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';
import { amplitudeDisplay, horizonLabel } from '@/src/utils/amplitude';
import { isLlmCandidateValid } from '@/src/utils/llm';
import { isGoldMarketClosed } from '@/src/utils/markets';
import { pctToPoints, pointSizeFor, priceDiffToPoints } from '@/src/utils/points';
import { formatLocal, parseUtcIso } from '@/src/utils/time';
import { useWatchlist } from '@/src/watchlist/WatchlistContext';

function directionColor(direction: string): string {
  switch (direction) {
    case 'long':
      return '#27ae60';
    case 'short':
      return '#c0392b';
    default:
      return '#7f8c8d';
  }
}

function timeUntil(targetIso: string): string {
  const target = parseUtcIso(targetIso);
  const diffMs = target.getTime() - Date.now();
  if (diffMs <= 0) return '';
  const totalMin = Math.floor(diffMs / 60_000);
  const days = Math.floor(totalMin / (60 * 24));
  const hours = Math.floor((totalMin % (60 * 24)) / 60);
  const mins = totalMin % 60;
  if (days > 0) return `dans ${days}j ${hours}h`;
  if (hours > 0) return `dans ${hours}h ${mins}min`;
  return `dans ${mins}min`;
}

/** Formate un pourcentage signé : +0.52% / -0.38% (signe explicite). */
function formatSignedPct(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
}

/** Formate un nombre de points signé : +180 pts / -95 pts. */
function formatSignedPts(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(0)} pts`;
}

/**
 * Convertit le mouvement brut du marché (delta_pct) en résultat DU PARI :
 * - long  → on profite de la hausse (delta tel quel)
 * - short → on profite de la baisse (delta inversé)
 * - neutral → pas de sens directionnel (le caller affiche le mouvement brut)
 * Miroir de `_gain_for` côté backend (scripts/backtest.py). C'est ce qui
 * fait que le signe du chiffre colle au badge vert/rouge.
 */
function gainPct(direction: string, deltaPct: number): number {
  if (direction === 'short') return -deltaPct;
  return deltaPct;
}

type TrState = 'correct' | 'sous_seuil' | 'raté' | 'en_attente' | 'données_manquantes';

/**
 * Verdict affiné d'une ligne de track record, en 3 états pour les signaux
 * directionnels (au lieu du binaire correct/raté du backend) :
 *  - correct    : mouvement DANS ton sens ≥ seuil
 *  - sous_seuil : mouvement plus petit que le seuil (bruit) → ni gagné ni
 *                 vraiment perdu. C'est le cas "+0.19% mais pastille rouge" :
 *                 bon sens, trop faible. On l'isole pour ne pas le confondre
 *                 avec une vraie perte.
 *  - raté       : mouvement CONTRE ton sens ≥ seuil (vraie perte)
 * en_attente / données_manquantes : repris tels quels du backend.
 *
 * Le backend (_success_for) ne renvoie que correct/raté ; on raffine ici
 * côté affichage à partir de delta_pct + threshold_pct, sans changer la
 * définition du hit rate.
 */
function effectiveState(row: TrackRecordRow, direction: string): TrState {
  if (row.badge === 'en_attente' || row.badge === 'données_manquantes') {
    return row.badge;
  }
  const dir = direction.toLowerCase();
  // Signaux neutres : on garde le verdict binaire du backend.
  if (row.delta_pct == null || (dir !== 'long' && dir !== 'short')) {
    return row.badge === 'correct' ? 'correct' : 'raté';
  }
  const gain = gainPct(dir, row.delta_pct);
  if (gain > row.threshold_pct) return 'correct';
  if (gain < -row.threshold_pct) return 'raté';
  return 'sous_seuil';
}

const STATE_COLOR: Record<string, string> = {
  correct: '#27ae60',
  sous_seuil: '#e67e22',
  raté: '#c0392b',
};

function TrackRecordBadge({
  state,
  targetIso,
  entityId,
}: {
  state: TrState;
  targetIso: string;
  entityId: string;
}) {
  switch (state) {
    case 'correct':
      return (
        <View style={[trStyles.badge, { backgroundColor: '#27ae60' }]}>
          <ThemedText style={trStyles.badgeText}>✓</ThemedText>
        </View>
      );
    case 'sous_seuil':
      return (
        <View style={[trStyles.badge, { backgroundColor: '#e67e22' }]}>
          <ThemedText style={trStyles.badgeText}>≈</ThemedText>
        </View>
      );
    case 'raté':
      return (
        <View style={[trStyles.badge, { backgroundColor: '#c0392b' }]}>
          <ThemedText style={trStyles.badgeText}>✗</ThemedText>
        </View>
      );
    case 'en_attente':
      return (
        <View style={[trStyles.badge, { backgroundColor: '#7f8c8d' }]}>
          <ThemedText style={trStyles.badgeText}>⏳</ThemedText>
        </View>
      );
    default:
      // données_manquantes : badge spécifique "marché fermé" si GOLD week-end.
      // Yahoo ne renvoie aucune bougie hors fenêtre forex (ven 22h UTC →
      // dim 22h UTC). Cause structurelle, pas un bug Tik.
      if (entityId === 'GOLD' && isGoldMarketClosed(targetIso)) {
        return (
          <View style={[trStyles.badge, { backgroundColor: '#34495e' }]}>
            <ThemedText style={trStyles.badgeText}>🌙</ThemedText>
          </View>
        );
      }
      return (
        <View style={[trStyles.badge, { backgroundColor: '#95a5a6' }]}>
          <ThemedText style={trStyles.badgeText}>?</ThemedText>
        </View>
      );
  }
}

function TrackRecordSection({
  signalId,
  client,
  borderColor,
}: {
  signalId: string;
  client: unknown;
  borderColor: string;
}) {
  const [record, setRecord] = useState<SignalTrackRecord | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getSignalTrackRecord(client as any, signalId);
        if (!cancelled) setRecord(data);
      } catch {
        // Échec silencieux : le track record est une feature optionnelle
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [signalId, client]);

  const cardStyle = [trStyles.card, { borderColor }];

  if (loading) {
    return (
      <ThemedView style={cardStyle}>
        <View style={trStyles.headerRow}>
          <ThemedText type="subtitle">Track record</ThemedText>
          <InfoTooltip entryKey="trackRecord" />
        </View>
        <ActivityIndicator size="small" style={{ marginTop: 8 }} />
      </ThemedView>
    );
  }

  if (!record) return null;

  // Conversion en points (montée/baisse) : taille du point selon l'instrument
  // + prix de référence (p0 = prix à l'émission, identique sur toutes les
  // lignes). Si l'un manque (instrument inconnu ou historique insuffisant),
  // on n'affiche pas le bloc points.
  const pointSize = pointSizeFor(record.entity_id);
  const refPrice = record.rows.find((r) => r.p0 != null)?.p0 ?? null;

  return (
    <ThemedView style={cardStyle}>
      <View style={trStyles.headerRow}>
        <ThemedText type="subtitle">Track record</ThemedText>
        <InfoTooltip entryKey="trackRecord" />
      </View>
      <ThemedText style={trStyles.subtitle}>
        Direction {record.direction.toUpperCase()} · horizon {record.horizon}
      </ThemedText>
      {record.rows.map((row) => {
        const eff = effectiveState(row, record.direction);
        const marketClosed =
          eff === 'données_manquantes' &&
          record.entity_id === 'GOLD' &&
          isGoldMarketClosed(row.target_iso);
        const dir = record.direction.toLowerCase();
        const directional = dir === 'long' || dir === 'short';

        // Le chiffre principal parle dans le sens du PARI, pas du marché :
        // pour un SHORT, un prix qui baisse = gain positif. Sa couleur suit
        // le verdict (vert/orange/rouge). Le mouvement brut du marché reste
        // visible dessous. Corrige la confusion "+ affiché avec une pastille
        // rouge" (cas "bon sens mais sous le seuil" → désormais orange ≈).
        let primary: string;
        let resultColor: string | undefined;
        let marketSub: string | null = null;
        if (eff === 'en_attente') {
          primary = timeUntil(row.target_iso);
        } else if (eff === 'données_manquantes') {
          primary = marketClosed ? 'marché GOLD fermé' : 'données non disponibles';
        } else if (row.delta_pct != null) {
          if (directional) {
            primary = formatSignedPct(gainPct(dir, row.delta_pct));
            resultColor = STATE_COLOR[eff];
            const movePts =
              pointSize != null && row.p0 != null && row.p1 != null
                ? ` · ${formatSignedPts(priceDiffToPoints(row.p1, row.p0, pointSize))}`
                : '';
            marketSub = `marché ${formatSignedPct(row.delta_pct)}${movePts}`;
          } else {
            // neutral : c'est l'amplitude du mouvement qui compte → brut.
            primary = formatSignedPct(row.delta_pct);
          }
        } else {
          primary = '—';
        }

        return (
          <View key={row.label} style={trStyles.row}>
            <ThemedText style={trStyles.label}>{row.label}</ThemedText>
            <TrackRecordBadge state={eff} targetIso={row.target_iso} entityId={record.entity_id} />
            <View style={trStyles.valueCol}>
              <ThemedText style={[trStyles.value, resultColor ? { color: resultColor } : null]}>
                {primary}
              </ThemedText>
              {marketSub ? <ThemedText style={trStyles.market}>{marketSub}</ThemedText> : null}
            </View>
            {eff === 'correct' || eff === 'sous_seuil' || eff === 'raté' ? (
              <ThemedText style={trStyles.threshold}>seuil {row.threshold_pct}%</ThemedText>
            ) : null}
          </View>
        );
      })}
      {['long', 'short'].includes(record.direction.toLowerCase()) ? (
        <ThemedText style={trStyles.legend}>
          ✓ vert = bon sens, mouvement ≥ seuil · ≈ orange = bon sens mais trop faible (sous le
          seuil) · ✗ rouge = mauvais sens. Le chiffre = résultat de ton pari ; « marché » =
          mouvement brut du prix.
        </ThemedText>
      ) : null}
      {/* Footer min-max dynamique : adapté aux 3 horizons (flash/swing/macro)
          dont les seuils diffèrent. Affiche "Seuil : X %" si min === max,
          sinon "Seuils : X % à Y % selon l'horizon mesuré". */}
      {(() => {
        const thresholds = record.rows.map((r) => r.threshold_pct);
        if (thresholds.length === 0) return null;
        const min = Math.min(...thresholds);
        const max = Math.max(...thresholds);
        const text =
          min === max
            ? `Seuil : ±${min}%`
            : `Seuils : ±${min}% à ±${max}% selon l'horizon mesuré`;
        return <ThemedText style={trStyles.note}>{text}</ThemedText>;
      })()}

      {/* Mouvement requis en points (montée/baisse) = seuil × prix de réf,
          converti via la taille du point de l'instrument. Symétrique (le seuil
          l'est). C'est l'amplitude à franchir pour valider, pas un objectif. */}
      {pointSize != null && refPrice != null ? (
        <ThemedView style={trStyles.pointsBlock}>
          <ThemedText style={trStyles.subtitle}>Mouvement requis en points</ThemedText>
          {record.rows.map((row) => {
            const pts = pctToPoints(row.threshold_pct, refPrice, pointSize);
            return (
              <View key={`pts-${row.label}`} style={trStyles.row}>
                <ThemedText style={trStyles.label}>{row.label}</ThemedText>
                <ThemedText style={trStyles.value}>
                  ▲ +{pts.toFixed(0)} pts{'   '}▼ -{pts.toFixed(0)} pts
                </ThemedText>
              </View>
            );
          })}
          <ThemedText style={trStyles.legend}>
            = seuil × prix de réf ({Math.round(refPrice)} · 1 pt = {pointSize} $). Symétrique :
            c&apos;est le mouvement à franchir pour VALIDER le signal, pas un objectif de gain.
            Taille du point ajustable dans src/utils/points.ts.
          </ThemedText>
        </ThemedView>
      ) : null}
    </ThemedView>
  );
}

export default function SignalDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { client } = useAuth();
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];
  const { isWatched, add, remove } = useWatchlist();

  const [signal, setSignal] = useState<Signal | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const watched = signal ? isWatched(signal.id) : false;
  const toggleWatch = useCallback(() => {
    if (!signal) return;
    if (watched) remove(signal.id);
    else add(signal);
  }, [signal, watched, add, remove]);

  const fetchSignal = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getSignal(client, id);
      setSignal(data);
    } catch (err) {
      const msg = err instanceof TikError ? err.message : (err as Error).message;
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [client, id]);

  useEffect(() => {
    void fetchSignal();
  }, [fetchSignal]);

  if (loading) {
    return (
      <ThemedView style={styles.center}>
        <ActivityIndicator size="large" />
      </ThemedView>
    );
  }

  if (error || !signal) {
    return (
      <ThemedView style={styles.center}>
        <ThemedText type="subtitle">Erreur</ThemedText>
        <ThemedText style={styles.errorText}>
          {error ?? 'Signal introuvable.'}
        </ThemedText>
        <Pressable
          onPress={() => void fetchSignal()}
          style={({ pressed }) => [
            styles.retry,
            { backgroundColor: palette.tint, opacity: pressed ? 0.7 : 1 },
          ]}>
          <ThemedText style={styles.retryLabel}>Réessayer</ThemedText>
        </Pressable>
      </ThemedView>
    );
  }

  const cardStyle = [
    styles.card,
    { borderColor: palette.icon },
  ];

  // Amplitude attendue (ADR-025) — volatilité typique sur l'horizon, en %
  // (+ points calibrés MT5 si dispo). Null pour les signaux pré-ADR-025.
  const ampl = amplitudeDisplay(
    signal.entity_id,
    signal.horizon,
    signal.advisory?.expected_amplitude_pct,
    signal.advisory?.ref_price,
  );

  return (
    <ScrollView contentContainerStyle={styles.scroll}>
      <ThemedView style={[cardStyle, styles.heroCard]}>
        <ThemedView style={[styles.heroHeader, { backgroundColor: 'transparent' }]}>
          <ThemedText type="title">{signal.entity_id}</ThemedText>
          <View
            style={[styles.directionBadge, { backgroundColor: directionColor(signal.direction) }]}>
            <ThemedText style={styles.directionLabel}>{signal.direction.toUpperCase()}</ThemedText>
          </View>
        </ThemedView>

        <View style={styles.heroSubtitleRow}>
          <ThemedText style={styles.heroSubtitle}>
            horizon {horizonLabel(signal.horizon)} • {signal.sources_count} sources
          </ThemedText>
          <InfoTooltip entryKey="horizon" />
        </View>

        <ThemedView style={[styles.metricsRow, { backgroundColor: 'transparent' }]}>
          <ThemedView style={[styles.metricBox, { backgroundColor: 'transparent' }]}>
            <View style={styles.metricLabelRow}>
              <ThemedText style={styles.metricLabel}>Conviction OSINT</ThemedText>
              <InfoTooltip entryKey="conviction" />
            </View>
            <ThemedText type="title" style={styles.metricValue}>
              {(signal.confidence * 100).toFixed(0)}%
            </ThemedText>
            <ThemedText style={styles.metricSubtitle}>
              magnitude du biais cross-validé
            </ThemedText>
          </ThemedView>
          <ThemedView style={[styles.metricBox, { backgroundColor: 'transparent' }]}>
            <View style={styles.metricLabelRow}>
              <ThemedText style={styles.metricLabel}>Veracity</ThemedText>
              <InfoTooltip entryKey="veracity" />
            </View>
            <ThemedText type="title" style={styles.metricValue}>
              {(signal.veracity * 100).toFixed(0)}%
            </ThemedText>
            <ThemedText style={styles.metricSubtitle}>
              alignement des sources
            </ThemedText>
          </ThemedView>
        </ThemedView>

        {ampl ? (
          <ThemedView style={[styles.amplBlock, { borderColor: palette.icon }]}>
            <ThemedText style={styles.amplLabel}>Amplitude attendue (volatilité)</ThemedText>
            <ThemedText style={styles.amplValue}>
              {ampl.pctLabel}
              {ampl.pointsLabel ? ` (${ampl.pointsLabel})` : ''} sur {ampl.windowLabel}
            </ThemedText>
            <ThemedText style={styles.amplNote}>
              {"Volatilité typique sur l'horizon — ce n'est PAS une prévision du sens."}
            </ThemedText>
          </ThemedView>
        ) : null}

        <ThemedText style={styles.metaLine}>
          Émis le {formatLocal(signal.timestamp)}
        </ThemedText>
        {signal.expiry ? (
          <ThemedText style={styles.metaLine}>
            Expire le {formatLocal(signal.expiry)}
          </ThemedText>
        ) : null}
        <AntiFakeNewsBadge status={signal.circuit_breaker_status} />
        {signal.advisory?.near_macro_event ? (
          <NearMacroBadge data={signal.advisory.near_macro_event} />
        ) : null}

        <Pressable
          onPress={toggleWatch}
          style={({ pressed }) => [
            styles.watchBtn,
            {
              borderColor: watched ? '#f1c40f' : palette.icon,
              backgroundColor: watched
                ? 'rgba(241, 196, 15, 0.12)'
                : 'transparent',
              opacity: pressed ? 0.6 : 1,
            },
          ]}
          accessibilityRole="button"
          accessibilityLabel={watched ? 'Retirer de la watchlist' : 'Ajouter à la watchlist'}>
          <ThemedText style={[styles.watchLabel, { color: watched ? '#b07d0a' : palette.text }]}>
            {watched ? '★ Suivi' : '☆ Suivre'}
          </ThemedText>
        </Pressable>
      </ThemedView>

      {/* Track record — chargé lazily après la hero card (Phase A.3 J+10) */}
      {id ? (
        <TrackRecordSection signalId={id} client={client} borderColor={palette.icon} />
      ) : null}

      {signal.hypothesis ? (
        <ThemedView style={cardStyle}>
          <ThemedText type="subtitle">Hypothèse</ThemedText>
          <ThemedText>{signal.hypothesis}</ThemedText>
        </ThemedView>
      ) : null}

      {/*
        Carte secondaire ADR-012 — affichée conditionnellement :
        - Mode shadow : Signal.advisory.llm_hypothesis_candidate présent
          ET de longueur ≥ 30 mots (filet anti-fantôme en cas de
          stockage par erreur d'un texte template court côté backend).
        - Mode active : Signal.advisory.template_hypothesis présent
          → on montre l'ancien texte template "pour référence" en audit
          permanent post-bascule.
        Si aucun des deux n'est présent (mode disabled ou Paquet 6 pas
        encore livré sur ce signal historique), la carte ne s'affiche pas.
      */}
      {isLlmCandidateValid(signal.advisory?.llm_hypothesis_candidate) ? (
        <ThemedView style={[cardStyle, styles.llmCard]}>
          <ThemedView style={[styles.llmHeader, { backgroundColor: 'transparent' }]}>
            <ThemedText type="subtitle">Hypothèse contextuelle</ThemedText>
            <ThemedView style={[styles.llmBadge, { backgroundColor: '#7f8c8d' }]}>
              <ThemedText style={styles.llmBadgeLabel}>LLM · validation</ThemedText>
            </ThemedView>
          </ThemedView>
          <ThemedText>{signal.advisory?.llm_hypothesis_candidate}</ThemedText>
        </ThemedView>
      ) : signal.advisory?.template_hypothesis ? (
        <ThemedView style={[cardStyle, styles.llmCard]}>
          <ThemedView style={[styles.llmHeader, { backgroundColor: 'transparent' }]}>
            <ThemedText type="subtitle">Hypothèse template</ThemedText>
            <ThemedView style={[styles.llmBadge, { backgroundColor: '#7f8c8d' }]}>
              <ThemedText style={styles.llmBadgeLabel}>référence</ThemedText>
            </ThemedView>
          </ThemedView>
          <ThemedText>{signal.advisory?.template_hypothesis}</ThemedText>
        </ThemedView>
      ) : null}

      <ThemedView style={cardStyle}>
        <ThemedText type="subtitle">
          Contre-scénarios ({signal.counter_scenarios.length})
        </ThemedText>
        {signal.counter_scenarios.length === 0 ? (
          <ThemedText style={{ opacity: 0.6 }}>Aucun contre-scénario fourni.</ThemedText>
        ) : (
          signal.counter_scenarios.map((cs, i) => (
            <ThemedView key={`${cs.name}-${i}`} style={[styles.subItem, { borderColor: palette.icon }]}>
              <ThemedText type="defaultSemiBold">{cs.name}</ThemedText>
              <ThemedText style={styles.subMeta}>
                probabilité {(cs.probability * 100).toFixed(0)}%
              </ThemedText>
              <ThemedText>{cs.mitigation}</ThemedText>
            </ThemedView>
          ))
        )}
      </ThemedView>

      <ThemedView style={cardStyle}>
        <ThemedText type="subtitle">Evidence ({signal.evidence.length})</ThemedText>
        {signal.evidence.length === 0 ? (
          <ThemedText style={{ opacity: 0.6 }}>Aucune evidence rattachée.</ThemedText>
        ) : (
          signal.evidence.map((ev, i) => (
            <ThemedView key={`${ev.source}-${i}`} style={[styles.subItem, { borderColor: palette.icon }]}>
              <ThemedView style={[styles.evHeader, { backgroundColor: 'transparent' }]}>
                <ThemedText type="defaultSemiBold">{ev.source}</ThemedText>
                <ThemedText style={styles.subMeta}>
                  score {(ev.score * 100).toFixed(0)}%
                </ThemedText>
              </ThemedView>
              <ThemedText>{ev.fact}</ThemedText>
            </ThemedView>
          ))
        )}
      </ThemedView>

      {(() => {
        // Décisionnels = triggers qui pèsent dans la décision (poids > 0) :
        // sentiment OSINT en swing, microstructure (orderbook/agression) en
        // flash. Technique (RSI/EMA/MACD/momentum) = poids 0 depuis ADR-018 →
        // replié dans "Contexte technique" pour ne pas laisser croire qu'il
        // décide quoi que ce soit.
        const decisionTriggers = signal.triggers.filter((t) => t.weight > 0);
        const techTriggers = signal.triggers.filter((t) => t.weight <= 0);

        const renderTrigger = (tg: (typeof signal.triggers)[number], i: number) => (
          <ThemedView key={`${tg.type}-${i}`} style={[styles.subItem, { borderColor: palette.icon }]}>
            <ThemedView style={[styles.evHeader, { backgroundColor: 'transparent' }]}>
              <ThemedText type="defaultSemiBold">{tg.type}</ThemedText>
              <ThemedText style={styles.subMeta}>poids {(tg.weight * 100).toFixed(0)}%</ThemedText>
            </ThemedView>
            <ThemedText>{tg.value}</ThemedText>
          </ThemedView>
        );

        return (
          <ThemedView style={cardStyle}>
            <ThemedText type="subtitle">
              Triggers décisionnels ({decisionTriggers.length})
            </ThemedText>
            {decisionTriggers.length === 0 ? (
              <ThemedText style={{ opacity: 0.6 }}>Aucun trigger décisionnel (poids &gt; 0).</ThemedText>
            ) : (
              decisionTriggers.map(renderTrigger)
            )}

            {techTriggers.length > 0 ? (
              <ThemedView style={{ backgroundColor: 'transparent', marginTop: 10 }}>
                <Collapsible
                  title={`Contexte technique (${techTriggers.length}) — n'influence pas la décision`}>
                  <ThemedText style={{ opacity: 0.6, fontSize: 12, marginBottom: 6 }}>
                    Indicateurs techniques (RSI / EMA / MACD / momentum) fournis à titre informatif
                    (poids 0). Depuis le refactor ADR-018, Tik décide sur ses overlays cross-validés
                    (sentiment OSINT en swing, microstructure en flash), pas sur la technique.
                  </ThemedText>
                  {techTriggers.map(renderTrigger)}
                </Collapsible>
              </ThemedView>
            ) : null}
          </ThemedView>
        );
      })()}

      {signal.advisory?.notes || signal.advisory?.macro_crash_warning || signal.advisory?.bias_on_existing_positions ? (
        <ThemedView style={cardStyle}>
          <ThemedText type="subtitle">Advisory</ThemedText>
          {signal.advisory?.macro_crash_warning ? (
            <ThemedView style={[styles.cbWarn, { backgroundColor: 'rgba(192, 57, 43, 0.12)' }]}>
              <ThemedText style={{ color: '#c0392b', fontWeight: '600' }}>
                Macro crash warning actif
              </ThemedText>
            </ThemedView>
          ) : null}
          {signal.advisory?.bias_on_existing_positions ? (
            <ThemedText>
              Biais sur positions ouvertes : {signal.advisory?.bias_on_existing_positions}
            </ThemedText>
          ) : null}
          {signal.advisory?.notes ? <ThemedText>{signal.advisory?.notes}</ThemedText> : null}
        </ThemedView>
      ) : null}

      <ThemedView style={[cardStyle, styles.idCard]}>
        <ThemedText style={{ fontSize: 11, opacity: 0.5 }}>{signal.id}</ThemedText>
      </ThemedView>
    </ScrollView>
  );
}

// ----- Styles track record -----

const trStyles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  subtitle: {
    fontSize: 12,
    opacity: 0.6,
    marginBottom: 2,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 4,
  },
  label: {
    width: 32,
    fontWeight: '600',
    fontSize: 13,
  },
  badge: {
    width: 24,
    height: 24,
    borderRadius: 4,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '700',
  },
  valueCol: {
    flex: 1,
  },
  value: {
    fontSize: 14,
    fontWeight: '600',
  },
  market: {
    fontSize: 11,
    opacity: 0.5,
    marginTop: 1,
  },
  legend: {
    fontSize: 11,
    opacity: 0.55,
    marginTop: 6,
    lineHeight: 15,
  },
  pointsBlock: {
    backgroundColor: 'transparent',
    marginTop: 12,
  },
  threshold: {
    fontSize: 11,
    opacity: 0.5,
  },
  note: {
    fontSize: 11,
    opacity: 0.45,
    marginTop: 4,
  },
});

// ----- Styles principaux -----

const styles = StyleSheet.create({
  scroll: {
    padding: 16,
    gap: 12,
    paddingBottom: 32,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 12,
  },
  errorText: {
    color: '#c0392b',
    textAlign: 'center',
  },
  retry: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 8,
  },
  retryLabel: {
    color: '#ffffff',
    fontWeight: '600',
  },
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  heroCard: {
    gap: 12,
  },
  heroHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  directionBadge: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
  },
  directionLabel: {
    color: '#ffffff',
    fontWeight: '700',
    fontSize: 12,
    letterSpacing: 0.5,
  },
  heroSubtitle: {
    fontSize: 13,
    opacity: 0.7,
    textTransform: 'lowercase',
  },
  heroSubtitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  metricsRow: {
    flexDirection: 'row',
    gap: 16,
    marginTop: 4,
  },
  metricBox: {
    flex: 1,
  },
  metricLabelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  metricLabel: {
    fontSize: 12,
    opacity: 0.6,
  },
  metricValue: {
    fontSize: 28,
    lineHeight: 32,
  },
  metricSubtitle: {
    fontSize: 10,
    opacity: 0.5,
    marginTop: 2,
    fontStyle: 'italic',
  },
  metaLine: {
    fontSize: 12,
    opacity: 0.6,
  },
  amplBlock: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    marginTop: 8,
    gap: 2,
  },
  amplLabel: {
    fontSize: 12,
    opacity: 0.6,
  },
  amplValue: {
    fontSize: 18,
    fontWeight: '700',
  },
  amplNote: {
    fontSize: 10,
    opacity: 0.5,
    fontStyle: 'italic',
  },
  cbWarn: {
    padding: 8,
    borderRadius: 6,
    marginTop: 4,
  },
  subItem: {
    borderWidth: 1,
    borderRadius: 8,
    padding: 10,
    gap: 4,
    marginTop: 4,
  },
  subMeta: {
    fontSize: 12,
    opacity: 0.6,
  },
  evHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  idCard: {
    paddingVertical: 8,
    alignItems: 'center',
  },
  llmCard: {
    backgroundColor: 'rgba(127, 140, 141, 0.06)',
  },
  llmHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  llmBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
  },
  llmBadgeLabel: {
    color: '#ffffff',
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 0.4,
  },
  watchBtn: {
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 16,
    alignItems: 'center',
    marginTop: 4,
  },
  watchLabel: {
    fontSize: 14,
    fontWeight: '600',
    letterSpacing: 0.3,
  },
});
