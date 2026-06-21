/**
 * Observatoire — vue orbitale des sources (refonte γ, maquettes « orbital view »).
 *
 * Page dédiée (PAS un onglet — vue de contexte « prendre du recul », atteinte
 * depuis l'onglet Sources). Un soleil par actif (bascule BTC / GOLD) entouré de
 * ses sources OSINT réelles, colorées par leur santé. Tap une source → ce qu'elle
 * dit (texte verbatim) + sa fraîcheur.
 *
 * Honnêteté (Axe #1) : la version « influence chiffrée » des maquettes est
 * volontairement ABANDONNÉE (poids inventés vs moyenne non pondérée ADR-004). On
 * ne montre que des faits. Données réelles via les hooks existants (zéro backend).
 */

import { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { CosmicOrbital } from '@/components/cosmic/cosmic-orbital';
import { CosmicRelations } from '@/components/cosmic/cosmic-relations';
import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import { useDashboardKpis } from '@/src/hooks/useDashboardKpis';
import { useSourceHealth } from '@/src/hooks/useSourceHealth';
import { buildOrbitalModel, type OrbitalEntity } from '@/src/sources/orbital';
import { buildRelationsModel } from '@/src/sources/relations';

const ENTITIES: OrbitalEntity[] = ['BTC', 'GOLD'];
type ViewMode = 'orbital' | 'relations';

export default function ObservatoireScreen() {
  const insets = useSafeAreaInsets();
  const [mode, setMode] = useState<ViewMode>('orbital');
  const [entity, setEntity] = useState<OrbitalEntity>('BTC');

  const { signals24h, loading: signalsLoading } = useDashboardKpis();
  const { health, loading: healthLoading } = useSourceHealth();

  const model = useMemo(
    () => buildOrbitalModel(entity, signals24h, health),
    [entity, signals24h, health],
  );
  const relations = useMemo(
    () => buildRelationsModel(signals24h, health),
    [signals24h, health],
  );

  const loading = signalsLoading && healthLoading;

  return (
    <CosmicBackground>
      <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + 6 }]}>
        <View style={styles.header}>
          <Text style={styles.brand}>L&apos;observatoire</Text>
          <Text style={styles.brandTag}>Les sources qui alimentent le signal</Text>
        </View>

        <Text style={styles.intro}>
          {mode === 'orbital'
            ? 'Chaque actif est un soleil ; ses sources OSINT gravitent autour. La couleur dit leur santé, le tap révèle ce qu’elles disent vraiment — sans aucun « poids » inventé.'
            : 'BTC et GOLD vus ensemble : les sources propres à chacun, et au centre celle(s) qui alimentent les deux (le « pont »). La couleur d’un trait dit la santé de la source.'}
        </Text>

        {/* Bascule de vue : Orbital (un soleil) / Relations (deux soleils) */}
        <View style={styles.toggleRow}>
          {(['orbital', 'relations'] as ViewMode[]).map((m) => {
            const active = mode === m;
            return (
              <Pressable
                key={m}
                onPress={() => setMode(m)}
                style={({ pressed }) => [
                  styles.pill,
                  active ? styles.pillActive : null,
                  { opacity: pressed ? 0.7 : 1 },
                ]}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}>
                <Text style={[styles.pillText, active ? styles.pillTextActive : null]}>
                  {m === 'orbital' ? '◐ Par actif' : '✦ Relations'}
                </Text>
              </Pressable>
            );
          })}
        </View>

        {mode === 'orbital' ? (
          <>
            {/* Bascule actif (mode orbital seulement) */}
            <View style={styles.toggleRow}>
              {ENTITIES.map((e) => {
                const active = entity === e;
                return (
                  <Pressable
                    key={e}
                    onPress={() => setEntity(e)}
                    style={({ pressed }) => [
                      styles.pill,
                      active ? styles.pillActive : null,
                      { opacity: pressed ? 0.7 : 1 },
                    ]}
                    accessibilityRole="button"
                    accessibilityState={{ selected: active }}>
                    <Text style={[styles.pillText, active ? styles.pillTextActive : null]}>{e}</Text>
                  </Pressable>
                );
              })}
            </View>

            <CosmicOrbital model={model} />
          </>
        ) : (
          <CosmicRelations model={relations} />
        )}

        {loading ? <Text style={styles.loading}>Sondage des sources…</Text> : null}

        <Text style={styles.footer}>
          Vue de contexte. Tik n&apos;a aucun edge directionnel prouvé (NO-GO 2026-05-27) — observer
          ≠ parier.
        </Text>
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
  header: {
    gap: 3,
  },
  brand: {
    ...TitleShadow.glow,
    fontFamily: serifTitleFamily,
    color: Cosmic.accent,
    fontSize: 28,
    fontStyle: 'italic',
    fontWeight: '700',
  },
  brandTag: {
    color: Cosmic.textFaint,
    fontSize: 9,
    letterSpacing: 1.5,
    textTransform: 'uppercase',
    fontFamily: Fonts.mono,
  },
  intro: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 19,
  },
  toggleRow: {
    flexDirection: 'row',
    gap: 8,
  },
  pill: {
    paddingVertical: 7,
    paddingHorizontal: 20,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: Cosmic.border,
    backgroundColor: 'rgba(255,255,255,0.03)',
  },
  pillActive: {
    borderColor: 'rgba(255,193,94,0.45)',
    backgroundColor: 'rgba(255,193,94,0.14)',
  },
  pillText: {
    fontFamily: Fonts.mono,
    color: Cosmic.textDim,
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 1,
  },
  pillTextActive: {
    color: Cosmic.accent,
  },
  loading: {
    color: Cosmic.textFaint,
    fontSize: 12,
    fontStyle: 'italic',
    textAlign: 'center',
  },
  footer: {
    color: Cosmic.textFaint,
    fontSize: 12,
    fontStyle: 'italic',
    marginTop: 4,
  },
});
