/**
 * Page détail d'un signal — version cosmique (refonte γ, bout 2).
 *
 * ROUTE DÉDIÉE au flux cosmique uniquement (`/signal-cosmique/[id]`). Elle est
 * ouverte par la liste cosmique (`CosmicSignalRow`) et la carte riche
 * (`CosmicSignalCard` variant summary). Les anciens onglets (Signals/Watchlist/
 * Alerts encore en thème clair) continuent d'utiliser `app/signal/[id].tsx`
 * intact → pas d'incohérence visuelle mid-refonte. Au bout 5 (promotion du
 * cosmique en vrai onglet), on consolidera.
 *
 * Le héros en haut est la `CosmicSignalCard` (variant `detail` : non cliquable,
 * sans teaser, l'évidence et les contre-scénarios sont rendus en entier plus
 * bas). TOUTE la logique métier est conservée à l'identique de l'ancienne page :
 *   - track record 3 états (correct / sous_seuil / raté) + en_attente / manquant
 *   - conversion en points MT5 (montée/baisse) selon l'instrument
 *   - badge « marché GOLD fermé » le week-end
 *   - hypothèse LLM vs template (ADR-012), triggers décisionnels vs technique
 *
 * Zéro backend touché. Les badges anti-fake-news / proximité macro et le
 * collapsible sont ré-rendus en cosmique inline (les composants partagés
 * dépendent du thème clair/sombre de l'appareil et jureraient sur le fond forcé).
 */

import { useLocalSearchParams, useRouter } from 'expo-router';
import { type ReactNode, useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { CosmicSignalCard } from '@/components/cosmic/cosmic-signal-card';
import { InfoTooltip } from '@/components/ui/info-tooltip';
import { Cosmic, TitleShadow } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import { getSignal, getSignalTrackRecord } from '@/src/api/endpoints';
import { TikError } from '@/src/api/errors';
import type { NearMacroEvent, Signal, SignalTrackRecord, TrackRecordRow } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';
import { isLlmCandidateValid } from '@/src/utils/llm';
import { isGoldMarketClosed } from '@/src/utils/markets';
import { pctToPoints, pointSizeFor, priceDiffToPoints } from '@/src/utils/points';
import { formatLocal, parseUtcIso } from '@/src/utils/time';
import { useWatchlist } from '@/src/watchlist/WatchlistContext';

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
 * Miroir de `_gain_for` côté backend (scripts/backtest.py).
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
 *                 vraiment perdu (cas « +0.19% mais sous le seuil »).
 *  - raté       : mouvement CONTRE ton sens ≥ seuil (vraie perte)
 * en_attente / données_manquantes : repris tels quels du backend.
 *
 * Le backend (_success_for) ne renvoie que correct/raté ; on raffine ici côté
 * affichage à partir de delta_pct + threshold_pct, sans changer le hit rate.
 */
function effectiveState(row: TrackRecordRow, direction: string): TrState {
  if (row.badge === 'en_attente' || row.badge === 'données_manquantes') {
    return row.badge;
  }
  const dir = direction.toLowerCase();
  if (row.delta_pct == null || (dir !== 'long' && dir !== 'short')) {
    return row.badge === 'correct' ? 'correct' : 'raté';
  }
  const gain = gainPct(dir, row.delta_pct);
  if (gain > row.threshold_pct) return 'correct';
  if (gain < -row.threshold_pct) return 'raté';
  return 'sous_seuil';
}

// Couleur du chiffre résultat (texte clair sur fond sombre → palette douce).
const STATE_COLOR: Record<string, string> = {
  correct: Cosmic.long,
  sous_seuil: Cosmic.neutral,
  raté: Cosmic.short,
};

// Fond des petits badges ✓/≈/✗ : versions plus saturées pour rester lisibles
// avec un glyphe blanc (les couleurs douces de la palette manquent de contraste
// sur une si petite surface). En_attente / manquant en gris bleuté neutre.
const TR_BADGE_BG: Record<TrState, string> = {
  correct: '#3fae86',
  sous_seuil: '#d99a3c',
  raté: '#d85f5f',
  en_attente: '#5b6b8c',
  données_manquantes: '#6b7280',
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
  let symbol: string;
  let bg: string;
  switch (state) {
    case 'correct':
      symbol = '✓';
      bg = TR_BADGE_BG.correct;
      break;
    case 'sous_seuil':
      symbol = '≈';
      bg = TR_BADGE_BG.sous_seuil;
      break;
    case 'raté':
      symbol = '✗';
      bg = TR_BADGE_BG.raté;
      break;
    case 'en_attente':
      symbol = '⏳';
      bg = TR_BADGE_BG.en_attente;
      break;
    default:
      // données_manquantes : badge « marché fermé 🌙 » si GOLD le week-end.
      // Yahoo ne renvoie aucune bougie hors fenêtre forex — cause structurelle.
      if (entityId === 'GOLD' && isGoldMarketClosed(targetIso)) {
        symbol = '🌙';
        bg = '#3d4a63';
      } else {
        symbol = '?';
        bg = TR_BADGE_BG.données_manquantes;
      }
  }
  return (
    <View style={[trStyles.badge, { backgroundColor: bg }]}>
      <Text style={trStyles.badgeText}>{symbol}</Text>
    </View>
  );
}

function TrackRecordSection({ signalId, client }: { signalId: string; client: unknown }) {
  const [record, setRecord] = useState<SignalTrackRecord | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getSignalTrackRecord(client as never, signalId);
        if (!cancelled) setRecord(data);
      } catch {
        // Échec silencieux : le track record est une feature optionnelle.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [signalId, client]);

  if (loading) {
    return (
      <View style={styles.card}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Track record</Text>
          <InfoTooltip entryKey="trackRecord" />
        </View>
        <ActivityIndicator size="small" color={Cosmic.accent} style={{ marginTop: 8 }} />
      </View>
    );
  }

  if (!record) return null;

  const pointSize = pointSizeFor(record.entity_id);
  const refPrice = record.rows.find((r) => r.p0 != null)?.p0 ?? null;
  const directionalRecord = ['long', 'short'].includes(record.direction.toLowerCase());

  return (
    <View style={styles.card}>
      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Track record</Text>
        <InfoTooltip entryKey="trackRecord" />
      </View>
      <Text style={trStyles.subtitle}>
        Direction {record.direction.toUpperCase()} · horizon {record.horizon}
      </Text>

      {record.rows.map((row) => {
        const eff = effectiveState(row, record.direction);
        const marketClosed =
          eff === 'données_manquantes' &&
          record.entity_id === 'GOLD' &&
          isGoldMarketClosed(row.target_iso);
        const dir = record.direction.toLowerCase();
        const directional = dir === 'long' || dir === 'short';

        // Le chiffre principal parle dans le sens du PARI, pas du marché : pour
        // un SHORT, un prix qui baisse = gain positif. Sa couleur suit le verdict
        // (vert/orange/rouge). Le mouvement brut du marché reste visible dessous.
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
            primary = formatSignedPct(row.delta_pct);
          }
        } else {
          primary = '—';
        }

        return (
          <View key={row.label} style={trStyles.row}>
            <Text style={trStyles.label}>{row.label}</Text>
            <TrackRecordBadge state={eff} targetIso={row.target_iso} entityId={record.entity_id} />
            <View style={trStyles.valueCol}>
              <Text style={[trStyles.value, resultColor ? { color: resultColor } : null]}>
                {primary}
              </Text>
              {marketSub ? <Text style={trStyles.market}>{marketSub}</Text> : null}
            </View>
            {eff === 'correct' || eff === 'sous_seuil' || eff === 'raté' ? (
              <Text style={trStyles.threshold}>seuil {row.threshold_pct}%</Text>
            ) : null}
          </View>
        );
      })}

      {directionalRecord ? (
        <Text style={trStyles.legend}>
          {'✓ vert = bon sens, mouvement ≥ seuil · ≈ orange = bon sens mais trop faible (sous le ' +
            "seuil) · ✗ rouge = mauvais sens. Le chiffre = résultat de ton pari ; « marché » = " +
            'mouvement brut du prix.'}
        </Text>
      ) : null}

      {/* Footer min-max dynamique (les 3 horizons ont des seuils différents). */}
      {(() => {
        const thresholds = record.rows.map((r) => r.threshold_pct);
        if (thresholds.length === 0) return null;
        const min = Math.min(...thresholds);
        const max = Math.max(...thresholds);
        const text =
          min === max
            ? `Seuil : ±${min}%`
            : `Seuils : ±${min}% à ±${max}% selon l'horizon mesuré`;
        return <Text style={trStyles.note}>{text}</Text>;
      })()}

      {/* Mouvement requis en points = seuil × prix de réf, converti via la taille
          du point de l'instrument. Symétrique. C'est l'amplitude à franchir pour
          valider, pas un objectif de gain. */}
      {pointSize != null && refPrice != null ? (
        <View style={trStyles.pointsBlock}>
          <Text style={trStyles.subtitle}>Mouvement requis en points</Text>
          {record.rows.map((row) => {
            const pts = pctToPoints(row.threshold_pct, refPrice, pointSize);
            return (
              <View key={`pts-${row.label}`} style={trStyles.row}>
                <Text style={trStyles.label}>{row.label}</Text>
                <Text style={trStyles.value}>
                  ▲ +{pts.toFixed(0)} pts{'   '}▼ -{pts.toFixed(0)} pts
                </Text>
              </View>
            );
          })}
          <Text style={trStyles.legend}>
            {`= seuil × prix de réf (${Math.round(refPrice)} · 1 pt = ${pointSize} $). ` +
              "Symétrique : c'est le mouvement à franchir pour VALIDER le signal, pas un " +
              'objectif de gain. Taille du point ajustable dans src/utils/points.ts.'}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

/** Flag anti-fake-news (ADR-011) rendu en cosmique inline. */
function AfnFlag({ status }: { status: string }) {
  let color: string;
  let label: string;
  let desc: string;
  if (status === 'degraded') {
    color = Cosmic.neutral;
    label = '⚠ Anti fake-news : sources en désaccord';
    desc =
      'Au moins 2 sources de sentiment divergent fortement sur ce signal. ' +
      'Direction inchangée, mais à interpréter avec prudence (ADR-011).';
  } else if (status === 'tripped') {
    color = Cosmic.short;
    label = '🚫 Anti fake-news : bloqué';
    desc =
      'Outliers détectés ou désaccord critique entre sources. La direction a été ' +
      'forcée à « neutral » par sécurité ; le signal original est conservé en audit.';
  } else {
    return null; // status === 'ok' ou inconnu → pas de flag.
  }
  return (
    <View style={[styles.flagBox, { borderColor: color + '88', backgroundColor: color + '14' }]}>
      <Text style={[styles.flagTitle, { color }]}>{label}</Text>
      <Text style={styles.flagDesc}>{desc}</Text>
    </View>
  );
}

/** Repère de discipline « event macro HIGH proche » (ADR-017), cosmique inline. */
function NearMacroFlag({ data }: { data: NearMacroEvent }) {
  const router = useRouter();
  const dur = Math.abs(data.hours_until);
  const totalMin = Math.round(dur * 60);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  const durLabel = h <= 0 ? `${m} min` : m === 0 ? `${h} h` : `${h} h ${m} min`;
  const sens = data.hours_until >= 0 ? 'avant' : 'après';
  return (
    <Pressable
      onPress={() => router.push('/macro')}
      accessibilityRole="button"
      accessibilityLabel="Voir le calendrier macro"
      style={[styles.flagBox, { borderColor: Cosmic.accent + '88', backgroundColor: Cosmic.accent + '12' }]}>
      <Text style={[styles.flagTitle, { color: Cosmic.accent }]}>
        📅 Discipline macro — {data.event_code} ({data.importance})
      </Text>
      <Text style={styles.flagDesc}>
        {formatLocal(data.scheduled_for)} · émis ~{durLabel} {sens} {data.event_code}
      </Text>
      <Text style={styles.flagDesc}>
        {'Règle ±4h (Garde-fou 2-bis) : ne pas entrer en swing dans la fenêtre, ou sizing ' +
          'divisé par 2 (0,5 %). Forte volatilité attendue autour de l’événement.'}
      </Text>
      <Text style={styles.flagHint}>Appuyer pour voir le calendrier macro ›</Text>
    </Pressable>
  );
}

/** Collapsible cosmique minimal (le composant partagé dépend du thème clair). */
function CosmicCollapsible({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <View style={{ marginTop: 10 }}>
      <Pressable onPress={() => setOpen((v) => !v)} style={styles.collapsibleHeading}>
        <Text style={styles.collapsibleArrow}>{open ? '▾' : '▸'}</Text>
        <Text style={styles.collapsibleTitle}>{title}</Text>
      </Pressable>
      {open ? <View style={{ marginTop: 6 }}>{children}</View> : null}
    </View>
  );
}

export default function SignalDetailCosmicScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { client } = useAuth();
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
      <CosmicBackground>
        <View style={styles.center}>
          <ActivityIndicator size="large" color={Cosmic.accent} />
        </View>
      </CosmicBackground>
    );
  }

  if (error || !signal) {
    return (
      <CosmicBackground>
        <View style={styles.center}>
          <Text style={styles.errorTitle}>Erreur</Text>
          <Text style={styles.errorText}>{error ?? 'Signal introuvable.'}</Text>
          <Pressable
            onPress={() => void fetchSignal()}
            style={({ pressed }) => [styles.retry, { opacity: pressed ? 0.7 : 1 }]}>
            <Text style={styles.retryLabel}>Réessayer</Text>
          </Pressable>
        </View>
      </CosmicBackground>
    );
  }

  // Triggers décisionnels (poids > 0) vs contexte technique (poids 0, ADR-018).
  const decisionTriggers = signal.triggers.filter((t) => t.weight > 0);
  const techTriggers = signal.triggers.filter((t) => t.weight <= 0);
  const renderTrigger = (tg: (typeof signal.triggers)[number], i: number) => (
    <View key={`${tg.type}-${i}`} style={styles.subItem}>
      <View style={styles.subHeader}>
        <Text style={styles.subName}>{tg.type}</Text>
        <Text style={styles.subMeta}>poids {(tg.weight * 100).toFixed(0)}%</Text>
      </View>
      <Text style={styles.subBody}>{tg.value}</Text>
    </View>
  );

  return (
    <CosmicBackground>
      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Héros : la décision d'un coup d'œil (carte cosmique, non cliquable) */}
        <CosmicSignalCard entityId={signal.entity_id} signal={signal} variant="detail" />

        {/* Discipline / flags (visibles, pas derrière un tap) */}
        <AfnFlag status={signal.circuit_breaker_status} />
        {signal.advisory?.near_macro_event ? (
          <NearMacroFlag data={signal.advisory.near_macro_event} />
        ) : null}

        {/* Suivre (watchlist) */}
        <Pressable
          onPress={toggleWatch}
          style={({ pressed }) => [
            styles.watchBtn,
            {
              borderColor: watched ? Cosmic.accent : Cosmic.borderStrong,
              backgroundColor: watched ? 'rgba(245,176,66,0.12)' : 'transparent',
              opacity: pressed ? 0.6 : 1,
            },
          ]}
          accessibilityRole="button"
          accessibilityLabel={watched ? 'Retirer de la watchlist' : 'Ajouter à la watchlist'}>
          <Text style={[styles.watchLabel, { color: watched ? Cosmic.accent : Cosmic.text }]}>
            {watched ? '★ Suivi' : '☆ Suivre'}
          </Text>
        </Pressable>

        {/* Track record */}
        {id ? <TrackRecordSection signalId={id} client={client} /> : null}

        {/* Hypothèse principale */}
        {signal.hypothesis ? (
          <View style={styles.card}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Hypothèse</Text>
              <InfoTooltip entryKey="hypothesis" />
            </View>
            <Text style={styles.bodyText}>{signal.hypothesis}</Text>
          </View>
        ) : null}

        {/* Hypothèse contextuelle LLM (shadow) ou template (audit) — ADR-012 */}
        {isLlmCandidateValid(signal.advisory?.llm_hypothesis_candidate) ? (
          <View style={[styles.card, styles.llmCard]}>
            <View style={styles.llmHeader}>
              <Text style={styles.sectionTitle}>Hypothèse contextuelle</Text>
              <View style={styles.llmBadge}>
                <Text style={styles.llmBadgeLabel}>LLM · validation</Text>
              </View>
            </View>
            <Text style={styles.bodyText}>{signal.advisory?.llm_hypothesis_candidate}</Text>
          </View>
        ) : signal.advisory?.template_hypothesis ? (
          <View style={[styles.card, styles.llmCard]}>
            <View style={styles.llmHeader}>
              <Text style={styles.sectionTitle}>Hypothèse template</Text>
              <View style={styles.llmBadge}>
                <Text style={styles.llmBadgeLabel}>référence</Text>
              </View>
            </View>
            <Text style={styles.bodyText}>{signal.advisory?.template_hypothesis}</Text>
          </View>
        ) : null}

        {/* Contre-scénarios (liste complète) */}
        <View style={styles.card}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Contre-scénarios ({signal.counter_scenarios.length})</Text>
            <InfoTooltip entryKey="counterScenarios" />
          </View>
          {signal.counter_scenarios.length === 0 ? (
            <Text style={styles.emptyText}>Aucun contre-scénario fourni.</Text>
          ) : (
            signal.counter_scenarios.map((cs, i) => (
              <View key={`${cs.name}-${i}`} style={styles.subItem}>
                <Text style={styles.subName}>{cs.name}</Text>
                <Text style={styles.subMeta}>probabilité {(cs.probability * 100).toFixed(0)}%</Text>
                <Text style={styles.subBody}>{cs.mitigation}</Text>
              </View>
            ))
          )}
        </View>

        {/* Evidence (liste complète) */}
        <View style={styles.card}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Evidence ({signal.evidence.length})</Text>
            <InfoTooltip entryKey="evidence" />
          </View>
          {signal.evidence.length === 0 ? (
            <Text style={styles.emptyText}>Aucune evidence rattachée.</Text>
          ) : (
            signal.evidence.map((ev, i) => (
              <View key={`${ev.source}-${i}`} style={styles.subItem}>
                <View style={styles.subHeader}>
                  <Text style={styles.subName}>{ev.source}</Text>
                  <Text style={styles.subMeta}>score {(ev.score * 100).toFixed(0)}%</Text>
                </View>
                <Text style={styles.subBody}>{ev.fact}</Text>
              </View>
            ))
          )}
        </View>

        {/* Triggers décisionnels + contexte technique (collapsible) */}
        <View style={styles.card}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Triggers décisionnels ({decisionTriggers.length})</Text>
            <InfoTooltip entryKey="triggers" />
          </View>
          {decisionTriggers.length === 0 ? (
            <Text style={styles.emptyText}>{'Aucun trigger décisionnel (poids > 0).'}</Text>
          ) : (
            decisionTriggers.map(renderTrigger)
          )}

          {techTriggers.length > 0 ? (
            <CosmicCollapsible
              title={`Contexte technique (${techTriggers.length}) — n'influence pas la décision`}>
              <Text style={styles.collapsibleNote}>
                {'Indicateurs techniques (RSI / EMA / MACD / momentum) fournis à titre informatif ' +
                  '(poids 0). Depuis le refactor ADR-018, Tik décide sur ses overlays cross-validés ' +
                  '(sentiment OSINT en swing, microstructure en flash), pas sur la technique.'}
              </Text>
              {techTriggers.map(renderTrigger)}
            </CosmicCollapsible>
          ) : null}
        </View>

        {/* Advisory (notes / warnings) */}
        {signal.advisory?.notes ||
        signal.advisory?.macro_crash_warning ||
        signal.advisory?.bias_on_existing_positions ? (
          <View style={styles.card}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Advisory</Text>
              <InfoTooltip entryKey="advisory" />
            </View>
            {signal.advisory?.macro_crash_warning ? (
              <View style={styles.cbWarn}>
                <Text style={styles.cbWarnText}>Macro crash warning actif</Text>
              </View>
            ) : null}
            {signal.advisory?.bias_on_existing_positions ? (
              <Text style={styles.bodyText}>
                Biais sur positions ouvertes : {signal.advisory?.bias_on_existing_positions}
              </Text>
            ) : null}
            {signal.advisory?.notes ? (
              <Text style={styles.bodyText}>{signal.advisory?.notes}</Text>
            ) : null}
          </View>
        ) : null}

        {/* Footer : dates + identifiant */}
        <View style={styles.metaCard}>
          <Text style={styles.metaLine}>Émis le {formatLocal(signal.timestamp)}</Text>
          {signal.expiry ? (
            <Text style={styles.metaLine}>Expire le {formatLocal(signal.expiry)}</Text>
          ) : null}
          <Text style={styles.idLine}>{signal.id}</Text>
        </View>
      </ScrollView>
    </CosmicBackground>
  );
}

// ----- Styles track record -----

const trStyles = StyleSheet.create({
  subtitle: {
    color: Cosmic.textDim,
    fontSize: 12,
    marginBottom: 2,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 4,
  },
  label: {
    color: Cosmic.text,
    width: 38,
    fontWeight: '600',
    fontSize: 13,
    fontFamily: Fonts.mono,
  },
  badge: {
    width: 24,
    height: 24,
    borderRadius: 5,
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
    color: Cosmic.text,
    fontSize: 14,
    fontWeight: '600',
  },
  market: {
    color: Cosmic.textFaint,
    fontSize: 11,
    marginTop: 1,
  },
  legend: {
    color: Cosmic.textFaint,
    fontSize: 11,
    marginTop: 6,
    lineHeight: 15,
  },
  threshold: {
    color: Cosmic.textFaint,
    fontSize: 11,
  },
  note: {
    color: Cosmic.textFaint,
    fontSize: 11,
    marginTop: 4,
  },
  pointsBlock: {
    marginTop: 12,
    gap: 2,
  },
});

// ----- Styles principaux -----

const styles = StyleSheet.create({
  scroll: {
    padding: 16,
    paddingBottom: 40,
    gap: 12,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 12,
  },
  errorTitle: {
    color: Cosmic.text,
    fontSize: 18,
    fontWeight: '700',
  },
  errorText: {
    color: Cosmic.short,
    textAlign: 'center',
    fontSize: 14,
  },
  retry: {
    paddingVertical: 10,
    paddingHorizontal: 18,
    borderRadius: 8,
    backgroundColor: Cosmic.accent,
  },
  retryLabel: {
    color: Cosmic.bgDeep,
    fontWeight: '700',
  },
  card: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
    gap: 8,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  sectionTitle: {
    ...TitleShadow.soft,
    color: Cosmic.accent,
    fontSize: 13,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  bodyText: {
    color: Cosmic.text,
    fontSize: 15,
    lineHeight: 23,
  },
  emptyText: {
    color: Cosmic.textDim,
    fontSize: 14,
  },
  flagBox: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 4,
  },
  flagTitle: {
    fontSize: 13,
    fontWeight: '700',
  },
  flagDesc: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 19,
  },
  flagHint: {
    color: Cosmic.textFaint,
    fontSize: 11,
    marginTop: 2,
  },
  watchBtn: {
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: 'center',
  },
  watchLabel: {
    fontSize: 14,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  subItem: {
    backgroundColor: Cosmic.cardAlt,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 10,
    padding: 11,
    gap: 4,
    marginTop: 6,
  },
  subHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 8,
  },
  subName: {
    color: Cosmic.text,
    fontSize: 15,
    fontWeight: '600',
    flex: 1,
  },
  subMeta: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontFamily: Fonts.mono,
  },
  subBody: {
    color: Cosmic.textDim,
    fontSize: 14,
    lineHeight: 20,
  },
  llmCard: {
    backgroundColor: 'rgba(125,158,211,0.06)',
  },
  llmHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  llmBadge: {
    backgroundColor: Cosmic.cardAlt,
    borderColor: Cosmic.border,
    borderWidth: 1,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
  },
  llmBadgeLabel: {
    color: Cosmic.macro,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  cbWarn: {
    backgroundColor: 'rgba(232,122,122,0.10)',
    borderColor: 'rgba(232,122,122,0.35)',
    borderWidth: 1,
    padding: 9,
    borderRadius: 8,
  },
  cbWarnText: {
    color: Cosmic.short,
    fontWeight: '700',
    fontSize: 13,
  },
  collapsibleHeading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 4,
  },
  collapsibleArrow: {
    color: Cosmic.textDim,
    fontSize: 13,
    width: 14,
  },
  collapsibleTitle: {
    color: Cosmic.textDim,
    fontSize: 13,
    fontWeight: '600',
    flex: 1,
  },
  collapsibleNote: {
    color: Cosmic.textFaint,
    fontSize: 13,
    lineHeight: 19,
    marginBottom: 6,
  },
  metaCard: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
    gap: 4,
  },
  metaLine: {
    color: Cosmic.textFaint,
    fontSize: 12,
  },
  idLine: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontFamily: Fonts.mono,
    marginTop: 2,
  },
});
