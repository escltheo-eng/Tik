/**
 * BrokerComparatorCard — comparateur de coûts brokers, en points.
 *
 * Affiché sur le détail d'un signal. Pour le mouvement favorable que TU vises
 * (objectif en points), montre ce que coûte le trade chez chaque broker une
 * fois retranchés spread + commission + swap, et désigne le moins cher.
 *
 * Logique pure dans `src/brokers/calc.ts`. Chiffres brokers dans
 * `src/brokers/config.ts` (à remplacer par tes vrais tarifs).
 *
 * Garde-fous / honnêteté :
 * - Les chiffres brokers par défaut sont des EXEMPLES (`verified: false`) →
 *   badge « à vérifier » tant que tu ne les as pas confirmés.
 * - La fiscalité n'est pas comptée (identique sur les deux brokers en France).
 * - Le levier est informatif (contrainte de marge), il ne change pas le gain
 *   en points.
 * - Réduire le coût n'améliore PAS l'edge directionnel de Tik (non démontré à
 *   ce jour — mesure décisive le 27/05).
 */

import { useMemo, useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { BROKER_SPECS } from '@/src/brokers/config';
import { compareBrokers } from '@/src/brokers/calc';

function parseNum(s: string): number | null {
  if (!s.trim()) return null;
  const v = parseFloat(s.replace(',', '.'));
  return Number.isFinite(v) ? v : null;
}

function fmtPts(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(0)} pts`;
}

export function BrokerComparatorCard({
  entityId,
  direction,
  borderColor,
}: {
  entityId: string;
  direction: string;
  borderColor: string;
}) {
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];

  const [objectif, setObjectif] = useState('');
  const [nights, setNights] = useState('');

  const dirLower = direction.toLowerCase();
  const isNeutral = dirLower !== 'long' && dirLower !== 'short';
  const tradeDir: 'long' | 'short' = dirLower === 'short' ? 'short' : 'long';

  const { results, bestId } = useMemo(
    () =>
      compareBrokers(BROKER_SPECS, {
        instrument: entityId,
        direction: tradeDir,
        grossFavorablePoints: parseNum(objectif),
        nights: parseNum(nights) ?? 0,
      }),
    [entityId, tradeDir, objectif, nights],
  );

  const inputStyle = [styles.input, { borderColor, color: palette.text }];

  return (
    <ThemedView style={[styles.card, { borderColor }]}>
      <ThemedText type="subtitle">Comparateur broker (coûts)</ThemedText>
      <ThemedText style={styles.subtitle}>
        Coût réel d&apos;un trade {entityId} {tradeDir.toUpperCase()}, en points, une fois
        retranchés spread + commission + swap.
      </ThemedText>

      {isNeutral ? (
        <ThemedText style={styles.note}>
          Signal neutre : pas de pari directionnel. Swap calculé en supposant LONG (ajuste
          si besoin).
        </ThemedText>
      ) : null}

      <View style={styles.inputsRow}>
        <View style={styles.inputCol}>
          <ThemedText style={styles.inputLabel}>Objectif (points)</ThemedText>
          <TextInput
            value={objectif}
            onChangeText={setObjectif}
            keyboardType="numeric"
            placeholder="ex. 800"
            placeholderTextColor={palette.icon}
            style={inputStyle}
          />
        </View>
        <View style={styles.inputCol}>
          <ThemedText style={styles.inputLabel}>Nuits détenues</ThemedText>
          <TextInput
            value={nights}
            onChangeText={setNights}
            keyboardType="numeric"
            placeholder="0"
            placeholderTextColor={palette.icon}
            style={inputStyle}
          />
        </View>
      </View>

      {results.length === 0 ? (
        <ThemedText style={styles.note}>
          Aucun paramètre broker pour {entityId}. Ajoute-le dans src/brokers/config.ts.
        </ThemedText>
      ) : (
        results.map((r) => {
          const best = r.brokerId === bestId;
          return (
            <View
              key={r.brokerId}
              style={[
                styles.brokerBlock,
                { borderColor: best ? '#27ae60' : borderColor },
              ]}
            >
              <View style={styles.brokerHeader}>
                <ThemedText style={styles.brokerName}>
                  {best ? '⭐ ' : ''}
                  {r.brokerName}
                </ThemedText>
                {!r.verified ? (
                  <ThemedText style={styles.unverified}>à vérifier</ThemedText>
                ) : null}
                <ThemedText style={styles.lev}>levier max {r.maxLeverage}</ThemedText>
              </View>
              <ThemedText style={styles.detail}>
                spread {r.spreadPoints} pts · commission {r.commissionPoints} pts · swap{' '}
                {fmtPts(r.swapPointsTotal)}
              </ThemedText>
              <ThemedText style={styles.detail}>
                seuil de rentabilité : {r.breakevenPoints.toFixed(0)} pts
                {r.netPoints != null ? (
                  <ThemedText
                    style={{ color: r.netPoints >= 0 ? '#27ae60' : '#c0392b', fontWeight: '700' }}
                  >
                    {'  ·  net à l’objectif : '}
                    {fmtPts(r.netPoints)}
                  </ThemedText>
                ) : null}
              </ThemedText>
            </View>
          );
        })
      )}

      <ThemedText style={styles.disclaimer}>
        ⚠️ Chiffres brokers = exemples à remplacer par tes vrais tarifs (src/brokers/config.ts).
        Fiscalité non comptée (identique sur les 2 brokers). Réduire le coût n&apos;améliore pas
        la qualité du pari Tik.
      </ThemedText>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  subtitle: {
    fontSize: 12,
    opacity: 0.6,
  },
  inputsRow: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 4,
  },
  inputCol: {
    flex: 1,
    gap: 4,
  },
  inputLabel: {
    fontSize: 12,
    opacity: 0.7,
  },
  input: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    fontSize: 15,
  },
  brokerBlock: {
    borderWidth: 1,
    borderRadius: 8,
    padding: 10,
    gap: 3,
    marginTop: 4,
  },
  brokerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  brokerName: {
    fontWeight: '700',
    fontSize: 14,
    flex: 1,
  },
  unverified: {
    fontSize: 10,
    color: '#e67e22',
    fontWeight: '700',
  },
  lev: {
    fontSize: 11,
    opacity: 0.5,
  },
  detail: {
    fontSize: 13,
  },
  note: {
    fontSize: 12,
    opacity: 0.6,
    fontStyle: 'italic',
  },
  disclaimer: {
    fontSize: 11,
    opacity: 0.55,
    marginTop: 6,
    lineHeight: 15,
  },
});
