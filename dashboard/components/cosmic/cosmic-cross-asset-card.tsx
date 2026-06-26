/**
 * CosmicCrossAssetCard — corrélations cross-asset du BTC (ADR-032, CONTEXTE strict).
 *
 * Montre AVEC QUOI le BTC co-bouge en ce moment : actions (S&P 500, Nasdaq), or,
 * dollar (DXY). Un label décrit le comportement (« comme un actif risqué », « comme
 * l'or », « découplé »), puis une barre divergente (−1 → +1) par actif.
 *
 * Honnêteté (Axe #1 / ADR-032) : une corrélation n'est NI une prédiction NI une
 * causalité — elle décrit un co-mouvement RÉCENT qui peut s'inverser. Couleur de
 * barre NEUTRE (le signe ≠ « bien/mal »). Ne touche jamais direction/veracity.
 */

import { StyleSheet, Text, View } from 'react-native';

import { UnavailableState } from './cosmic-unavailable-state';

import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import type { CrossAsset, CrossAssetCorr } from '@/src/api/types';
import { useTick } from '@/src/hooks/use-tick';
import { timeAgo } from '@/src/utils/time';

export interface CosmicCrossAssetCardProps {
  crossAsset: CrossAsset | null;
  loading?: boolean;
  error?: string | null;
}

interface BehaviorMeta {
  label: string;
  sub: string;
}

function behaviorMeta(b: string | null): BehaviorMeta {
  switch (b) {
    case 'risk_asset':
      return { label: 'Comme un actif risqué', sub: 'Le BTC suit les actions (Nasdaq / S&P 500)' };
    case 'digital_gold':
      return { label: "Comme l'or", sub: 'Le BTC co-bouge surtout avec le métal' };
    case 'decoupled':
      return { label: 'Découplé', sub: 'Le BTC évolue de façon autonome' };
    case 'mixed':
      return { label: 'Signaux mitigés', sub: 'Pas de co-mouvement dominant' };
    default:
      return { label: '—', sub: '' };
  }
}

/** Barre divergente (−1 → +1) centrée sur 0. Couleur neutre (signe ≠ bien/mal). */
function CorrBar({ corr }: { corr: number | null }) {
  if (corr == null) {
    return (
      <View style={styles.barTrack}>
        <View style={styles.barCenter} />
      </View>
    );
  }
  const c = Math.max(-1, Math.min(1, corr));
  const leftPct = (0.5 + Math.min(c, 0) * 0.5) * 100;
  const widthPct = Math.abs(c) * 50;
  return (
    <View style={styles.barTrack}>
      <View style={styles.barCenter} />
      <View style={[styles.barFill, { left: `${leftPct}%`, width: `${widthPct}%` }]} />
    </View>
  );
}

function fmtCorr(c: number | null): string {
  if (c == null) return '—';
  return `${c >= 0 ? '+' : ''}${c.toFixed(2)}`;
}

export function CosmicCrossAssetCard({ crossAsset, loading, error }: CosmicCrossAssetCardProps) {
  useTick(); // fraîcheur « il y a X » rafraîchie en temps réel
  const ca = crossAsset;
  const hasData = ca?.available && (ca?.assets?.length ?? 0) > 0;
  const meta = behaviorMeta(ca?.behavior ?? null);

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Corrélations</Text>
        <Text style={styles.periodLabel}>Yahoo · contexte</Text>
      </View>

      <Text style={styles.disclaimer}>
        Avec quoi le BTC bouge en ce moment (actions / or / dollar). Une corrélation n&apos;est ni
        une prédiction ni une cause — du contexte.
      </Text>

      {error ? (
        <UnavailableState kind="error" error={error} />
      ) : loading && !ca ? (
        <UnavailableState kind="loading" />
      ) : !hasData ? (
        <UnavailableState
          kind="empty"
          message="Aucune donnée collectée (l'ingester n'a pas encore publié)."
        />
      ) : (
        <View style={styles.body}>
          {/* Headline : comportement descriptif */}
          <View style={styles.behaviorBlock}>
            <View style={styles.badge}>
              <Text style={styles.badgeText}>{meta.label}</Text>
            </View>
            {meta.sub ? <Text style={styles.behaviorSub}>{meta.sub}</Text> : null}
          </View>

          {/* Barres de corrélation par actif */}
          <View style={styles.rows}>
            {ca!.assets.map((a: CrossAssetCorr) => (
              <View key={a.key ?? a.label ?? Math.random().toString()} style={styles.row}>
                <Text style={styles.rowLabel} numberOfLines={1}>
                  {a.label ?? a.key ?? '—'}
                </Text>
                <CorrBar corr={a.corr_recent} />
                <Text style={styles.rowValue}>{fmtCorr(a.corr_recent)}</Text>
              </View>
            ))}
          </View>

          <Text style={styles.scaleNote}>−1 (inverse) · 0 (indépendant) · +1 (synchrone)</Text>
          <Text style={styles.interpretation}>
            Corrélation des rendements journaliers sur ~30 jours de Bourse. Élevée vers les actions =
            le BTC se négocie comme un actif risqué ; vers l&apos;or = profil refuge ; proche de 0 =
            il évolue seul. Descriptif, pas une prédiction.
          </Text>

          {ca!.as_of ? (
            <Text style={styles.asof}>
              Données au {ca!.as_of} · il y a {timeAgo(ca!.as_of)}
            </Text>
          ) : null}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
    gap: 10,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 4,
  },
  title: {
    ...TitleShadow.soft,
    fontFamily: serifTitleFamily,
    color: Cosmic.text,
    fontSize: 16,
    fontWeight: '700',
  },
  periodLabel: { color: Cosmic.textFaint, fontSize: 12 },
  disclaimer: { color: Cosmic.textFaint, fontSize: 11, fontStyle: 'italic' },
  body: { gap: 10 },
  behaviorBlock: { gap: 4 },
  badge: {
    alignSelf: 'flex-start',
    backgroundColor: Cosmic.macro,
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 10,
  },
  badgeText: { color: '#10131c', fontSize: 13, fontWeight: '700' },
  behaviorSub: { color: Cosmic.textDim, fontSize: 12, lineHeight: 16 },
  rows: { gap: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  rowLabel: {
    color: Cosmic.text,
    fontSize: 12,
    fontWeight: '600',
    width: 80,
  },
  barTrack: {
    flex: 1,
    height: 10,
    borderRadius: 5,
    backgroundColor: 'rgba(255,255,255,0.06)',
    position: 'relative',
    overflow: 'hidden',
  },
  barCenter: {
    position: 'absolute',
    left: '50%',
    top: 0,
    bottom: 0,
    width: 1,
    backgroundColor: 'rgba(255,255,255,0.25)',
  },
  barFill: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    backgroundColor: Cosmic.macro,
    borderRadius: 5,
  },
  rowValue: {
    color: Cosmic.textDim,
    fontSize: 12,
    width: 44,
    textAlign: 'right',
    fontVariant: ['tabular-nums'],
  },
  scaleNote: { color: Cosmic.textFaint, fontSize: 10, textAlign: 'center' },
  interpretation: { color: Cosmic.textDim, fontSize: 12, lineHeight: 17 },
  asof: { color: Cosmic.textFaint, fontSize: 11, marginTop: 2 },
  emptyLabel: { color: Cosmic.textDim, fontSize: 13, paddingVertical: 8 },
  errorText: { color: Cosmic.short, fontSize: 13 },
});
