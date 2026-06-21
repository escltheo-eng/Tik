/**
 * CosmicRelations — vue « deux soleils » (relations structurelles) de l'observatoire.
 *
 * BTC (soleil haut) et GOLD (soleil bas) montrés ENSEMBLE. Entre eux, les sources :
 * celles PROPRES à BTC en haut, celles PROPRES à GOLD en bas, et au CENTRE le(s)
 * « pont(s) » — les sources qui alimentent les DEUX actifs (aujourd'hui : Google
 * News). Un trait relie chaque source à son ou ses soleil(s) ; sa couleur = la SANTÉ
 * de la source. Tap une source → ce qu'elle dit réellement (texte verbatim).
 *
 * Honnêteté (Axe #1 / ADR-004) : AUCUN « pourcentage d'influence ». La veracity est
 * une moyenne NON pondérée → aucune source ne pèse plus qu'une autre. Cette vue
 * montre une STRUCTURE (qui alimente quoi) + des FAITS (état, texte), jamais un poids.
 *
 * Géométrie en coordonnées FIXES (carré 320×480) → traits SVG et nœuds calés sur les
 * mêmes points → rendu stable et prévisible sur mobile (pas d'animation).
 */

import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Line } from 'react-native-svg';

import { Cosmic, directionMeta } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import {
  ageLabel,
  statusLabel,
  type OrbitalSource,
  type OrbitalStatus,
} from '@/src/sources/orbital';
import type { RelationsModel, SharedRelation } from '@/src/sources/relations';

const W = 320;
const H = 480;
const CX = W / 2;
const SUN_R = 33;
const BTC_SUN = { x: CX, y: 52 };
const GOLD_SUN = { x: CX, y: 428 };
const Y_BTC_ROW = 146;
const Y_SHARED_ROW = 240;
const Y_GOLD_ROW = 334;
const NODE_W = 76;

function rowX(i: number, n: number): number {
  if (n <= 1) return CX;
  const pad = 46;
  return pad + (i * (W - 2 * pad)) / (n - 1);
}

function statusColor(s: OrbitalStatus): string {
  switch (s) {
    case 'ok':
      return Cosmic.long;
    case 'stale':
      return Cosmic.neutral;
    case 'disabled':
      return Cosmic.textFaint;
    default:
      return Cosmic.short; // missing / muette
  }
}

/** Sélection : un nœud (source) d'un des trois groupes. */
type Sel =
  | { group: 'btc' | 'gold'; i: number }
  | { group: 'shared'; i: number }
  | null;

export function CosmicRelations({ model }: { model: RelationsModel }) {
  const [sel, setSel] = useState<Sel>(null);

  const btcDir = directionMeta(model.btc.direction ?? 'neutral');
  const goldDir = directionMeta(model.gold.direction ?? 'neutral');

  // Positions des nœuds (mêmes points que les extrémités des traits).
  const btcPos = model.btcOnly.map((_, i) => ({
    x: rowX(i, model.btcOnly.length),
    y: Y_BTC_ROW,
  }));
  const goldPos = model.goldOnly.map((_, i) => ({
    x: rowX(i, model.goldOnly.length),
    y: Y_GOLD_ROW,
  }));
  const sharedPos = model.shared.map((_, i) => ({
    x: rowX(i, model.shared.length),
    y: Y_SHARED_ROW,
  }));

  const selectedSource: OrbitalSource | SharedRelation | null =
    sel == null
      ? null
      : sel.group === 'btc'
        ? model.btcOnly[sel.i]
        : sel.group === 'gold'
          ? model.goldOnly[sel.i]
          : model.shared[sel.i];

  const isSel = (group: 'btc' | 'gold' | 'shared', i: number) =>
    sel?.group === group && sel.i === i;

  return (
    <View style={styles.wrap}>
      <View style={styles.headRow}>
        <Text style={styles.headTitle}>BTC ⇄ GOLD — qui alimente quoi</Text>
        <Text style={styles.headMeta}>
          {model.shared.length} source{model.shared.length > 1 ? 's' : ''} en commun
        </Text>
      </View>

      <View style={styles.system}>
        {/* Couche traits (sous les nœuds) */}
        <Svg width={W} height={H} style={StyleSheet.absoluteFill}>
          {/* BTC-only → soleil BTC */}
          {model.btcOnly.map((s, i) => (
            <Line
              key={`lb-${s.label}`}
              x1={btcPos[i].x}
              y1={btcPos[i].y}
              x2={BTC_SUN.x}
              y2={BTC_SUN.y}
              stroke={statusColor(s.status)}
              strokeWidth={1.6}
              opacity={s.status === 'ok' ? 0.55 : 0.28}
            />
          ))}
          {/* GOLD-only → soleil GOLD */}
          {model.goldOnly.map((s, i) => (
            <Line
              key={`lg-${s.label}`}
              x1={goldPos[i].x}
              y1={goldPos[i].y}
              x2={GOLD_SUN.x}
              y2={GOLD_SUN.y}
              stroke={statusColor(s.status)}
              strokeWidth={1.6}
              opacity={s.status === 'ok' ? 0.55 : 0.28}
            />
          ))}
          {/* Pont partagé → les DEUX soleils (deux traits, un peu plus marqués) */}
          {model.shared.map((sh, i) => (
            <Line
              key={`lsb-${sh.label}`}
              x1={sharedPos[i].x}
              y1={sharedPos[i].y}
              x2={BTC_SUN.x}
              y2={BTC_SUN.y}
              stroke={statusColor(sh.btc.status)}
              strokeWidth={2}
              opacity={sh.btc.status === 'ok' ? 0.6 : 0.3}
            />
          ))}
          {model.shared.map((sh, i) => (
            <Line
              key={`lsg-${sh.label}`}
              x1={sharedPos[i].x}
              y1={sharedPos[i].y}
              x2={GOLD_SUN.x}
              y2={GOLD_SUN.y}
              stroke={statusColor(sh.gold.status)}
              strokeWidth={2}
              opacity={sh.gold.status === 'ok' ? 0.6 : 0.3}
            />
          ))}
        </Svg>

        {/* Soleil BTC */}
        <Sun center={BTC_SUN} color={Cosmic.btcSun} label="BTC" />
        <SunTag
          y={BTC_SUN.y + SUN_R + 4}
          dir={model.btc.direction}
          dirMeta={btcDir}
          accord={model.btc.accord}
        />

        {/* Soleil GOLD */}
        <Sun center={GOLD_SUN} color={Cosmic.goldSun} label="GOLD" />
        <SunTag
          y={GOLD_SUN.y - SUN_R - 22}
          dir={model.gold.direction}
          dirMeta={goldDir}
          accord={model.gold.accord}
        />

        {/* Nœuds BTC-only */}
        {model.btcOnly.map((s, i) => (
          <SourceNode
            key={`nb-${s.label}`}
            source={s}
            pos={btcPos[i]}
            side="btc"
            selected={isSel('btc', i)}
            onPress={() => setSel(isSel('btc', i) ? null : { group: 'btc', i })}
          />
        ))}

        {/* Nœuds partagés (pont) */}
        {model.shared.map((sh, i) => (
          <SourceNode
            key={`ns-${sh.label}`}
            source={sh.btc}
            label={sh.label}
            pos={sharedPos[i]}
            side="shared"
            selected={isSel('shared', i)}
            onPress={() => setSel(isSel('shared', i) ? null : { group: 'shared', i })}
          />
        ))}

        {/* Nœuds GOLD-only */}
        {model.goldOnly.map((s, i) => (
          <SourceNode
            key={`ng-${s.label}`}
            source={s}
            pos={goldPos[i]}
            side="gold"
            selected={isSel('gold', i)}
            onPress={() => setSel(isSel('gold', i) ? null : { group: 'gold', i })}
          />
        ))}
      </View>

      {/* Panneau détail */}
      {selectedSource == null ? (
        <View style={styles.panel}>
          <Text style={styles.hintText}>
            Tape une source pour voir ce qu&apos;elle dit. La source du milieu (bleue) nourrit les
            deux actifs.
          </Text>
        </View>
      ) : sel?.group === 'shared' ? (
        <SharedPanel sh={selectedSource as SharedRelation} />
      ) : (
        <SourcePanel s={selectedSource as OrbitalSource} />
      )}

      <Text style={styles.honest}>
        Toutes les sources comptent à <Text style={styles.honestStrong}>parts égales</Text> (moyenne
        non pondérée) — aucun « poids » n&apos;est inventé.
      </Text>
      <Text style={styles.legend}>🟢 vivante · 🟠 en retard · 🔴 muette · ⚫ désactivée</Text>
    </View>
  );
}

function Sun({
  center,
  color,
  label,
}: {
  center: { x: number; y: number };
  color: string;
  label: string;
}) {
  return (
    <View
      style={[
        styles.sun,
        {
          left: center.x - SUN_R,
          top: center.y - SUN_R,
          backgroundColor: color,
          shadowColor: color,
        },
      ]}>
      <Text style={styles.sunLabel}>{label}</Text>
    </View>
  );
}

function SunTag({
  y,
  dir,
  dirMeta,
  accord,
}: {
  y: number;
  dir: string | null;
  dirMeta: { color: string; label: string };
  accord: number | null;
}) {
  return (
    <View style={[styles.sunTag, { top: y, borderColor: dir ? dirMeta.color : Cosmic.border }]}>
      <Text style={[styles.sunTagText, { color: dir ? dirMeta.color : Cosmic.textFaint }]}>
        {dir ? dirMeta.label : '—'}
        {accord != null ? ` · ${Math.round(accord * 100)}%` : ''}
      </Text>
    </View>
  );
}

function SourceNode({
  source,
  label,
  pos,
  side,
  selected,
  onPress,
}: {
  source: OrbitalSource;
  label?: string;
  pos: { x: number; y: number };
  side: 'btc' | 'gold' | 'shared';
  selected: boolean;
  onPress: () => void;
}) {
  // Pastille : santé de la source. EXCEPTION le pont (shared) a DEUX faces de santé
  // (une par actif, portées par les deux traits) → pastille bleue « pont », neutre,
  // pour ne pas afficher une face arbitraire. Les deux faces sont détaillées au tap.
  const color = side === 'shared' ? Cosmic.macro : statusColor(source.status);
  const dim = side !== 'shared' && (source.status === 'disabled' || source.status === 'missing');
  const border =
    side === 'shared'
      ? 'rgba(125,158,211,0.5)'
      : side === 'btc'
        ? 'rgba(245,176,66,0.32)'
        : 'rgba(232,200,115,0.32)';
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.node,
        {
          left: pos.x - NODE_W / 2,
          top: pos.y - 17,
          width: NODE_W,
          borderColor: selected ? Cosmic.accent : border,
          backgroundColor: selected ? 'rgba(255,193,94,0.12)' : 'rgba(10,12,20,0.92)',
          opacity: pressed ? 0.7 : 1,
        },
      ]}
      accessibilityRole="button"
      accessibilityLabel={`${label ?? source.label} — ${statusLabel(source.status)}`}>
      <View
        style={[styles.nodeDot, { backgroundColor: color, shadowColor: color, opacity: dim ? 0.5 : 1 }]}
      />
      <Text style={styles.nodeLabel} numberOfLines={1}>
        {label ?? source.label}
      </Text>
    </Pressable>
  );
}

function SourcePanel({ s }: { s: OrbitalSource }) {
  const color = statusColor(s.status);
  const tag = s.role === 'shadow' ? 'shadow (non enrôlée)' : s.role === 'disabled' ? 'désactivée' : null;
  return (
    <View style={[styles.panel, styles.panelSel]}>
      <View style={styles.panelHead}>
        <View style={styles.panelNameWrap}>
          <View style={[styles.panelOrb, { backgroundColor: color, shadowColor: color }]} />
          <Text style={styles.panelName}>{s.label}</Text>
          {tag ? <Text style={styles.panelRole}>{tag}</Text> : null}
        </View>
        <Text style={[styles.panelStatus, { color }]}>
          {statusLabel(s.status)} · {ageLabel(s.ageSeconds)}
        </Text>
      </View>
      {s.fact ? (
        <Text style={styles.panelFact}>{s.fact}</Text>
      ) : (
        <Text style={styles.panelFactMuted}>
          {s.status === 'disabled'
            ? 'Source désactivée — ne contribue pas au signal actuel.'
            : 'Pas de donnée dans le dernier signal (source absente ou muette).'}
        </Text>
      )}
      {s.note ? <Text style={styles.panelNote}>{s.note}</Text> : null}
    </View>
  );
}

/** Panneau d'une source PONT : ses deux faces (BTC + GOLD) côte à côte. */
function SharedPanel({ sh }: { sh: SharedRelation }) {
  return (
    <View style={[styles.panel, styles.panelSel]}>
      <View style={styles.panelHead}>
        <View style={styles.panelNameWrap}>
          <View style={[styles.panelOrb, { backgroundColor: Cosmic.macro, shadowColor: Cosmic.macro }]} />
          <Text style={styles.panelName}>{sh.label}</Text>
          <Text style={[styles.panelRole, { color: Cosmic.macro }]}>pont BTC ⇄ GOLD</Text>
        </View>
      </View>
      <Text style={styles.panelBridge}>
        Une seule source, deux flux : elle alimente le signal BTC <Text style={styles.bridgeStrong}>et</Text>{' '}
        le signal GOLD (deux requêtes distinctes).
      </Text>
      <SharedFace title="Côté BTC" s={sh.btc} />
      <SharedFace title="Côté GOLD" s={sh.gold} />
    </View>
  );
}

function SharedFace({ title, s }: { title: string; s: OrbitalSource }) {
  const color = statusColor(s.status);
  return (
    <View style={styles.face}>
      <View style={styles.faceHead}>
        <Text style={styles.faceTitle}>{title}</Text>
        <Text style={[styles.faceStatus, { color }]}>
          {statusLabel(s.status)} · {ageLabel(s.ageSeconds)}
        </Text>
      </View>
      {s.fact ? (
        <Text style={styles.faceFact}>{s.fact}</Text>
      ) : (
        <Text style={styles.panelFactMuted}>Pas de donnée dans le dernier signal.</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 16,
    padding: 14,
    gap: 12,
  },
  headRow: { gap: 2 },
  headTitle: {
    fontFamily: Fonts.mono,
    color: Cosmic.text,
    fontSize: 15,
    fontWeight: '800',
    letterSpacing: 0.3,
  },
  headMeta: { fontFamily: Fonts.mono, color: Cosmic.textDim, fontSize: 11 },
  system: { width: W, height: H, alignSelf: 'center', position: 'relative' },
  sun: {
    position: 'absolute',
    width: SUN_R * 2,
    height: SUN_R * 2,
    borderRadius: SUN_R,
    alignItems: 'center',
    justifyContent: 'center',
    shadowOpacity: 0.7,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 0 },
    elevation: 8,
  },
  sunLabel: {
    fontFamily: Fonts.mono,
    color: 'rgba(20,16,8,0.92)',
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  sunTag: {
    position: 'absolute',
    left: CX - 50,
    width: 100,
    alignItems: 'center',
    backgroundColor: 'rgba(6,7,13,0.85)',
    borderWidth: 1,
    borderRadius: 999,
    paddingVertical: 2,
  },
  sunTagText: {
    fontFamily: Fonts.mono,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  node: {
    position: 'absolute',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingVertical: 6,
    paddingHorizontal: 8,
    borderWidth: 1,
    borderRadius: 9,
  },
  nodeDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    flexShrink: 0,
    shadowOpacity: 0.9,
    shadowRadius: 5,
    shadowOffset: { width: 0, height: 0 },
  },
  nodeLabel: {
    fontFamily: Fonts.mono,
    color: Cosmic.textDim,
    fontSize: 9.5,
    flexShrink: 1,
  },
  panel: {
    backgroundColor: 'rgba(255,255,255,0.03)',
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 6,
  },
  panelSel: { borderColor: 'rgba(255,193,94,0.25)' },
  hintText: {
    color: Cosmic.textFaint,
    fontSize: 12,
    fontStyle: 'italic',
    textAlign: 'center',
    lineHeight: 17,
  },
  panelHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 8,
  },
  panelNameWrap: { flexDirection: 'row', alignItems: 'center', gap: 7, flexShrink: 1 },
  panelOrb: {
    width: 10,
    height: 10,
    borderRadius: 5,
    shadowOpacity: 0.9,
    shadowRadius: 5,
    shadowOffset: { width: 0, height: 0 },
  },
  panelName: { color: Cosmic.text, fontSize: 15, fontWeight: '700' },
  panelRole: {
    fontFamily: Fonts.mono,
    color: Cosmic.textFaint,
    fontSize: 9,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  panelStatus: { fontFamily: Fonts.mono, fontSize: 10, textAlign: 'right', flexShrink: 0 },
  panelFact: { fontFamily: Fonts.mono, color: Cosmic.text, fontSize: 12, lineHeight: 17 },
  panelFactMuted: { color: Cosmic.textDim, fontSize: 12, fontStyle: 'italic', lineHeight: 17 },
  panelNote: { color: Cosmic.textDim, fontSize: 11, lineHeight: 16 },
  panelBridge: { color: Cosmic.textDim, fontSize: 11, lineHeight: 16 },
  bridgeStrong: { color: Cosmic.macro, fontWeight: '700' },
  face: {
    backgroundColor: 'rgba(255,255,255,0.02)',
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 9,
    padding: 9,
    gap: 4,
  },
  faceHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 8,
  },
  faceTitle: {
    fontFamily: Fonts.mono,
    color: Cosmic.textDim,
    fontSize: 10,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  faceStatus: { fontFamily: Fonts.mono, fontSize: 9.5, flexShrink: 0 },
  faceFact: { fontFamily: Fonts.mono, color: Cosmic.text, fontSize: 11.5, lineHeight: 16 },
  honest: { color: Cosmic.textDim, fontSize: 11, lineHeight: 16 },
  honestStrong: { color: Cosmic.accent, fontWeight: '700' },
  legend: { color: Cosmic.textFaint, fontSize: 11 },
});
