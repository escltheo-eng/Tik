/** Libellés constellation — plus jamais deux points « Google News » indistinguables. */
import { describe, expect, it } from 'vitest';

import { sourceDisplayName } from '@/src/utils/source-labels';

describe('sourceDisplayName', () => {
  it("garde l'entité en suffixe — fin des doublons ambigus", () => {
    expect(sourceDisplayName('google_news_btc')).toBe('Google News BTC');
    expect(sourceDisplayName('google_news_gold')).toBe('Google News GOLD');
    expect(sourceDisplayName('polymarket_btc')).toBe('Polymarket BTC');
    expect(sourceDisplayName('polymarket_gold')).toBe('Polymarket GOLD');
    expect(sourceDisplayName('price_btc')).toBe('Prix BTC');
    expect(sourceDisplayName('price_gold')).toBe('Prix GOLD');
  });

  it('les paires BTC/GOLD produisent toujours des libellés distincts', () => {
    const pairs: [string, string][] = [
      ['google_news_btc', 'google_news_gold'],
      ['polymarket_btc', 'polymarket_gold'],
      ['price_btc', 'price_gold'],
    ];
    for (const [a, b] of pairs) {
      expect(sourceDisplayName(a)).not.toBe(sourceDisplayName(b));
    }
  });

  it('libellés spéciaux lisibles', () => {
    expect(sourceDisplayName('fear_greed')).toBe('Fear & Greed');
    expect(sourceDisplayName('cryptocompare_news')).toBe('CryptoCompare');
    expect(sourceDisplayName('gdelt_gold')).toBe('GDELT GOLD');
    expect(sourceDisplayName('reddit_btc')).toBe('Reddit BTC');
    expect(sourceDisplayName('hackernews_btc')).toBe('Hacker News BTC');
    expect(sourceDisplayName('binance_derivatives_btc')).toBe('Dérivés Binance BTC');
    expect(sourceDisplayName('btc_etf_flows')).toBe('Flux ETF BTC');
  });

  it('fallback title-case pour une source inconnue', () => {
    expect(sourceDisplayName('whale_alert')).toBe('Whale Alert');
  });
});
