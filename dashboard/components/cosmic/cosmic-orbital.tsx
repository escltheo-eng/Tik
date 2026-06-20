/**
 * CosmicOrbital — « observatoire » des sources d'un actif (refonte γ).
 *
 * Un soleil central (l'actif + sa direction + son accord) avec ses sources OSINT
 * en orbite. Couleur d'une source = sa SANTÉ (vivante / en retard / muette /
 * désactivée). Tap → panneau détail avec le TEXTE RÉEL que la source a produit
 * (evidence verbatim), sa fraîcheur, et la raison si elle est éteinte.
 *
 * Honnêteté (Axe #1 / ADR-004) : AUCUN « pourcentage d'influence » — la veracity
 * est une moyenne NON pondérée, donc aucune source ne pèse plus qu'une autre.
 * Cette vue montre des FAITS (sens, accord, état, texte), jamais un poids inventé.
 *
 * Données 100 % réelles (orbital.ts ← source_health + dernier signal swing).
 * Géométrie en positions absolues sur un carré de taille FIXE → rendu stable et
 * prévisible sur mobile (pas d'animation de rotation : trop coûteux, cf. maquette).
 */

import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Cosmic, directionMeta, sunColor } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import {
  ageLabel,
  statusLabel,
  type OrbitalModel,
  type OrbitalSource,
  type OrbitalStatus,
} from '@/src/sources/orbital';

const SIZE = 320;
const C = SIZE / 2;
const RING = 106;
const SAT = 78; // largeur de la boîte satellite

function satPos(i: number, n: number): { x: number; y: number } {
  const a = ((-90 + (i * 360) / n) * Math.PI) / 180;
  return { x: C + RING * Math.cos(a), y: C + RING * Math.sin(a) };
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

function roleTag(role: OrbitalSource['role']): string | null {
  if (role === 'shadow') return 'shadow (non enrôlée)';
  if (role === 'disabled') return 'désactivée';
  return null;
}

export function CosmicOrbital({ model }: { model: OrbitalModel }) {
  const [selected, setSelected] = useState<number | null>(null);

  const dir = directionMeta(model.direction ?? 'neutral');
  const sun = sunColor(model.entity);
  const n = model.sources.length;
  const sel = selected != null ? model.sources[selected] : null;

  return (
    <View style={styles.wrap}>
      {/* En-tête : actif + direction + accord du dernier swing */}
      <View style={styles.headRow}>
        <Text style={styles.headDir}>
          {model.entity} ·{' '}
          <Text style={{ color: model.direction ? dir.color : Cosmic.textFaint }}>
            {model.direction ? dir.label : 'pas de signal récent'}
          </Text>
        </Text>
        <Text style={styles.headMeta}>
          {model.accord != null ? `accord ${Math.round(model.accord * 100)}%` : '—'} ·{' '}
          {model.nAlive}/{model.nOverlays} vivantes
        </Text>
      </View>

      {/* Système solaire (carré fixe) */}
      <View style={styles.system}>
        {/* Orbites */}
        <View style={[styles.orbit, styles.orbitOuter]} />
        <View style={[styles.orbit, styles.orbitInner]} />

        {/* Soleil central */}
        <View
          style={[
            styles.sun,
            { backgroundColor: sun, shadowColor: sun },
          ]}>
          <Text style={styles.sunLabel}>{model.entity}</Text>
        </View>
        {/* Étiquette direction sous le soleil */}
        <View style={[styles.sunTag, { borderColor: model.direction ? dir.color : Cosmic.border }]}>
          <Text style={[styles.sunTagText, { color: model.direction ? dir.color : Cosmic.textFaint }]}>
            {model.direction ? dir.label : '—'}
          </Text>
        </View>

        {/* Satellites */}
        {model.sources.map((s, i) => {
          const { x, y } = satPos(i, n);
          const color = statusColor(s.status);
          const dim = s.status === 'disabled' || s.status === 'missing';
          const isSel = selected === i;
          return (
            <Pressable
              key={s.label}
              onPress={() => setSelected(isSel ? null : i)}
              style={({ pressed }) => [
                styles.sat,
                { left: x - SAT / 2, top: y - 24, width: SAT, opacity: pressed ? 0.6 : 1 },
              ]}
              accessibilityRole="button"
              accessibilityLabel={`${s.label} — ${statusLabel(s.status)}`}>
              <View
                style={[
                  styles.satDot,
                  {
                    backgroundColor: color,
                    shadowColor: color,
                    opacity: dim ? 0.5 : 1,
                  },
                  isSel ? styles.satDotSel : null,
                ]}
              />
              <Text
                style={[styles.satLabel, isSel ? { color: Cosmic.accent } : null]}
                numberOfLines={1}>
                {s.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* Panneau détail de la source sélectionnée */}
      {sel ? <DetailPanel s={sel} /> : <Hint />}

      {/* Rappel honnêteté + légende */}
      <Text style={styles.honest}>
        Toutes les sources comptent à <Text style={styles.honestStrong}>parts égales</Text> (moyenne
        non pondérée) — aucun « poids » n&apos;est inventé.
      </Text>
      <Text style={styles.legend}>🟢 vivante · 🟠 en retard · 🔴 muette · ⚫ désactivée</Text>
    </View>
  );
}

function Hint() {
  return (
    <View style={styles.panel}>
      <Text style={styles.hintText}>Tape une source pour voir ce qu&apos;elle dit.</Text>
    </View>
  );
}

function DetailPanel({ s }: { s: OrbitalSource }) {
  const color = statusColor(s.status);
  const tag = roleTag(s.role);
  return (
    <View style={[styles.panel, { borderColor: 'rgba(255,193,94,0.25)' }]}>
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

      {/* Ce que la source dit réellement (verbatim) */}
      {s.fact ? (
        <Text style={styles.panelFact}>{s.fact}</Text>
      ) : (
        <Text style={styles.panelFactMuted}>
          {s.status === 'disabled'
            ? 'Source désactivée — ne contribue pas au signal actuel.'
            : "Pas de donnée dans le dernier signal (source absente ou muette)."}
        </Text>
      )}

      {/* Raison / note */}
      {s.note ? <Text style={styles.panelNote}>{s.note}</Text> : null}

      {/* Crédibilité — avec le rappel qu'elle n'influe PAS sur l'accord (A12) */}
      {s.credibility != null ? (
        <Text style={styles.panelCred}>
          Fiabilité éditoriale {Math.round(s.credibility * 100)}% — n&apos;influe pas sur l&apos;accord.
        </Text>
      ) : null}
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
  headRow: {
    gap: 2,
  },
  headDir: {
    fontFamily: Fonts.mono,
    color: Cosmic.text,
    fontSize: 16,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  headMeta: {
    fontFamily: Fonts.mono,
    color: Cosmic.textDim,
    fontSize: 11,
  },
  system: {
    width: SIZE,
    height: SIZE,
    alignSelf: 'center',
    position: 'relative',
  },
  orbit: {
    position: 'absolute',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.07)',
    borderRadius: 999,
  },
  orbitOuter: {
    width: RING * 2,
    height: RING * 2,
    left: C - RING,
    top: C - RING,
  },
  orbitInner: {
    width: 124,
    height: 124,
    left: C - 62,
    top: C - 62,
    borderStyle: 'dashed',
    borderColor: 'rgba(255,255,255,0.05)',
  },
  sun: {
    position: 'absolute',
    width: 76,
    height: 76,
    borderRadius: 38,
    left: C - 38,
    top: C - 38,
    alignItems: 'center',
    justifyContent: 'center',
    shadowOpacity: 0.7,
    shadowRadius: 22,
    shadowOffset: { width: 0, height: 0 },
    elevation: 8,
  },
  sunLabel: {
    fontFamily: Fonts.mono,
    color: 'rgba(20,16,8,0.92)',
    fontSize: 13,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  sunTag: {
    position: 'absolute',
    left: C - 44,
    top: C + 42,
    width: 88,
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
    letterSpacing: 0.5,
  },
  sat: {
    position: 'absolute',
    alignItems: 'center',
    gap: 4,
  },
  satDot: {
    width: 14,
    height: 14,
    borderRadius: 7,
    shadowOpacity: 0.9,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 0 },
    elevation: 4,
  },
  satDotSel: {
    borderWidth: 2,
    borderColor: Cosmic.accent,
    width: 16,
    height: 16,
    borderRadius: 8,
  },
  satLabel: {
    fontFamily: Fonts.mono,
    color: Cosmic.textDim,
    fontSize: 9,
    textAlign: 'center',
  },
  panel: {
    backgroundColor: 'rgba(255,255,255,0.03)',
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 6,
  },
  hintText: {
    color: Cosmic.textFaint,
    fontSize: 12,
    fontStyle: 'italic',
    textAlign: 'center',
  },
  panelHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 8,
  },
  panelNameWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    flexShrink: 1,
  },
  panelOrb: {
    width: 10,
    height: 10,
    borderRadius: 5,
    shadowOpacity: 0.9,
    shadowRadius: 5,
    shadowOffset: { width: 0, height: 0 },
  },
  panelName: {
    color: Cosmic.text,
    fontSize: 15,
    fontWeight: '700',
  },
  panelRole: {
    fontFamily: Fonts.mono,
    color: Cosmic.textFaint,
    fontSize: 9,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  panelStatus: {
    fontFamily: Fonts.mono,
    fontSize: 10,
    textAlign: 'right',
    flexShrink: 0,
  },
  panelFact: {
    fontFamily: Fonts.mono,
    color: Cosmic.text,
    fontSize: 12,
    lineHeight: 17,
  },
  panelFactMuted: {
    color: Cosmic.textDim,
    fontSize: 12,
    fontStyle: 'italic',
    lineHeight: 17,
  },
  panelNote: {
    color: Cosmic.textDim,
    fontSize: 11,
    lineHeight: 16,
  },
  panelCred: {
    color: Cosmic.textFaint,
    fontSize: 10,
    fontStyle: 'italic',
  },
  honest: {
    color: Cosmic.textDim,
    fontSize: 11,
    lineHeight: 16,
  },
  honestStrong: {
    color: Cosmic.accent,
    fontWeight: '700',
  },
  legend: {
    color: Cosmic.textFaint,
    fontSize: 11,
  },
});
