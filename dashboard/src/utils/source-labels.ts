/**
 * Libellés des sources de la constellation (CosmicSourceHealth).
 *
 * Découvert le 2026-07-02 (captures trader) : l'ancien `prettyName` supprimait
 * le suffixe `_btc` / `_gold` → la constellation affichait des doublons
 * ambigus (« Google News » ×2, « Polymarket » ×2, « Price » ×2) — impossible
 * de savoir quel point était rouge pour quel actif. On garde désormais
 * l'entité en suffixe explicite (« Google News GOLD »).
 *
 * Fonction pure — testée dans __tests__/source-labels.test.ts.
 */

/** Bases dont le title-case brut serait faux ou peu lisible. */
const BASE_LABELS: Record<string, string> = {
  'fear greed': 'Fear & Greed',
  'cryptocompare news': 'CryptoCompare',
  'google news': 'Google News',
  gdelt: 'GDELT',
  reddit: 'Reddit',
  hackernews: 'Hacker News',
  price: 'Prix',
  'binance derivatives': 'Dérivés Binance',
  'btc etf flows': 'Flux ETF BTC',
};

/** `google_news_gold` → « Google News GOLD », `price_btc` → « Prix BTC ». */
export function sourceDisplayName(name: string): string {
  const entityMatch = name.match(/_(btc|gold)$/i);
  const entity = entityMatch ? entityMatch[1].toUpperCase() : null;
  const base = name
    .replace(/_(btc|gold)$/i, '')
    .replace(/_/g, ' ')
    .trim();
  const pretty =
    BASE_LABELS[base.toLowerCase()] ?? base.replace(/\b\w/g, (c) => c.toUpperCase());
  return entity ? `${pretty} ${entity}` : pretty;
}
