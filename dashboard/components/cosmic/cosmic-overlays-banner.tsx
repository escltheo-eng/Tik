/**
 * CosmicOverlaysBanner — alerte « BTC swing dégradé : N/4 sources actives ».
 *
 * La DIRECTION du BTC swing est construite par cross-validation de 4 overlays
 * sentiment (Fear & Greed, CryptoCompare, Google News, Reddit). Quand certains
 * sont morts (Reddit IP-banni Bug 11, CryptoCompare hors quota Bug 15…), la
 * direction repose sur moins de sources → signaux moins fiables, souvent un seul
 * point de vue dominant (FG « achète-la-peur »).
 *
 * Cette bannière rend ce trou VISIBLE (au lieu de le laisser silencieux dans
 * source_health). Honnêteté / Axe #1 : on signale la dégradation, on ne la
 * masque pas. Composant 100 % front (dérivé de `useSourceHealth`, déjà pollé) :
 * aucun changement backend, hot-reload. Ne s'affiche QUE si < 4/4 overlays OK.
 */

import { StyleSheet, Text, View } from 'react-native';

import { Cosmic } from '@/constants/cosmic';
import { useSourceHealth } from '@/src/hooks/useSourceHealth';

// Les 4 overlays sentiment qui construisent la direction du BTC swing.
// Clés = `name` exposé par /metrics/source_health (cf. SOURCE_SPECS backend).
const BTC_SWING_OVERLAYS: Record<string, string> = {
  fear_greed: 'Fear & Greed',
  cryptocompare_news: 'CryptoCompare',
  google_news_btc: 'Google News',
  reddit_btc: 'Reddit',
};
const TOTAL = Object.keys(BTC_SWING_OVERLAYS).length; // 4 (canonique)

export function CosmicOverlaysBanner() {
  const { health } = useSourceHealth();
  if (!health) return null; // pas encore chargé / injoignable → pas de bannière

  const activeNames = new Set(
    health.sources.filter((s) => s.name in BTC_SWING_OVERLAYS && s.status === 'ok').map((s) => s.name),
  );
  if (activeNames.size >= TOTAL) return null; // 4/4 → rien à signaler

  const missing = Object.entries(BTC_SWING_OVERLAYS)
    .filter(([key]) => !activeNames.has(key))
    .map(([, label]) => label);

  return (
    <View style={styles.banner}>
      <Text style={styles.title}>
        ⚠ BTC swing dégradé — {activeNames.size}/{TOTAL} sources actives
      </Text>
      <Text style={styles.body}>
        Manquant : {missing.join(', ')}. La direction BTC repose sur moins de sources → signaux moins
        fiables, souvent un seul point de vue dominant. Ne pas lire les LONG « achète-la-peur » comme
        un achat (NO-GO inchangé).
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    borderWidth: 1,
    borderColor: Cosmic.short,
    borderRadius: 12,
    paddingVertical: 9,
    paddingHorizontal: 11,
    backgroundColor: 'rgba(232,122,122,0.10)',
    gap: 3,
  },
  title: {
    color: Cosmic.short,
    fontSize: 13,
    fontWeight: '700',
  },
  body: {
    color: Cosmic.textDim,
    fontSize: 12,
    lineHeight: 17,
  },
});
