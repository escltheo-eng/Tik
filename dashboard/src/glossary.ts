export interface GlossaryEntry {
  term: string;
  short: string;
  long: string;
  ref?: string;
}

export const GLOSSARY: Record<string, GlossaryEntry> = {
  veracity: {
    term: 'Veracity',
    short:
      "Alignement des sources OSINT cross-validées sur ce signal. Affichée en %. " +
      "70 % = sources divergent fortement, 95 % = toutes alignées.",
    long:
      "Mesure dynamique entre 70 % et 95 % calculée à partir de la dispersion des biais OSINT (Fear & Greed, news, Reddit, GDELT, FRED). " +
      "Plus les sources sont alignées sur la même direction, plus la veracity monte. " +
      "Paliers : 95 % dispersion ≤ 0.20 / 90 % ≤ 0.40 / 85 % ≤ 0.60 / 78 % ≤ 0.80 / 70 % au-delà. " +
      "Garde-fou 2-bis transitoire (Reddit IP-bannie) : seuil minimum 85 % pour swing BTC en trading manuel J+24.",
    ref: 'ADR-018',
  },
  conviction: {
    term: 'Conviction OSINT',
    short:
      "Affichée en %, mesure entre 0 % et 100 %. < 30 % = marché OSINT équilibré (signal neutral). " +
      "30-50 % = conviction faible. 50-80 % = moyenne. > 80 % = forte conviction directionnelle.",
    long:
      "Égal à |combined_bias| × 100 où combined_bias est la moyenne des biais des overlays OSINT actifs, sources outliers neutralisées par l'anti fake-news (ADR-011). " +
      "Depuis le refactor OSINT pur ADR-018, ce champ ne reflète plus la force d'une analyse technique RSI/MACD/EMA — il quantifie uniquement la conviction OSINT. " +
      "La direction (long/short/neutral) est dérivée du signe de combined_bias avec seuil ±30 %. " +
      "Sous 30 %, le signal est systématiquement marqué neutral. " +
      "Le champ JSON s'appelle encore 'confidence' pour rétrocompatibilité des signaux historiques.",
    ref: 'ADR-018 + SDK 0.6.0',
  },
  afn: {
    term: 'Anti fake-news (AFN)',
    short:
      "Cross-validation des sources. degraded = drapeau prudence, tripped = direction forcée neutral.",
    long:
      "Détection statistique des sources OSINT qui divergent anormalement du consensus (Modified Z-score d'Iglewicz-Hoaglin + dispersion globale). " +
      "Le statut 'degraded' (orange) signale qu'au moins 2 sources sentiment divergent fortement — le signal est émis avec direction inchangée mais à interpréter avec prudence. " +
      "Le statut 'tripped' (rouge) signale des outliers détectés ou un désaccord critique — la direction est forcée à 'neutral' par sécurité. " +
      "Pattern soft filtering : Tik flagge et avertit, ne supprime pas le signal.",
    ref: 'ADR-011',
  },
  trackRecord: {
    term: 'Track record',
    short:
      "Performance réelle du signal mesurée à 4 horizons après son émission.",
    long:
      "Pour chaque signal, le delta de prix est mesuré à 4 horizons adaptés à son type : " +
      "flash (15min / 30min / 45min / 1h), swing (1h / 6h / 24h / 5j), macro (1j / 7j / 30j / 90j). " +
      "Badges : ✓ correct (delta dans la bonne direction et magnitude > seuil), ✗ raté (delta dans la mauvaise direction), " +
      "⏳ en attente (horizon dans le futur), ⚠ données manquantes (prix indisponible : weekend GOLD, retard ingestion). " +
      "Outil de calibration empirique signal-par-signal complémentaire du Hit rate global.",
    ref: 'Paquet 17',
  },
  horizon: {
    term: 'Horizon',
    short:
      "Échelle temporelle du signal. flash = minutes-heures, swing = heures-jours, macro = semaines-mois.",
    long:
      "Tik produit des signaux sur 3 horizons en parallèle : " +
      "flash (TTL 1h, klines 1m Binance, BTC uniquement car Yahoo a 15 min de délai sur GOLD), " +
      "swing (TTL 7j, klines 1h, BTC + GOLD), " +
      "macro (semaines-mois, klines 1j). " +
      "Chaque horizon a ses propres overlays et seuils. " +
      "Pour le trading manuel J+24, swing BTC est l'horizon le plus exploitable.",
    ref: 'ADR-005',
  },
  seuil: {
    term: 'Seuil de directionnalité',
    short:
      "Conviction minimale pour produire un signal directionnel. Fixé à 30 %. " +
      "Sous 30 % conviction = signal neutral systématiquement.",
    long:
      "Le seuil ±30 % sur le combined_bias OSINT cross-validé décide si la direction du signal est 'long' (>+30 %), 'short' (<-30 %) ou 'neutral' (entre les deux). " +
      "C'est pour ça qu'un signal affiché à 17 % conviction est toujours neutral. " +
      "Calibré au pifomètre raisonné après l'audit méthodique 2026-05-07. " +
      "Sera révisé empiriquement post-J+30 sur dataset diversifié.",
    ref: 'ADR-018',
  },
  combinedBias: {
    term: 'Combined bias',
    short:
      "Biais OSINT agrégé entre -100 % et +100 %. Moyenne des biais des overlays cross-validés.",
    long:
      "Moyenne des biais retournés par chaque overlay OSINT actif (FG, news, Reddit, GDELT, FRED selon entity). " +
      "Sources flaggées outliers par l'anti fake-news (ADR-011) sont neutralisées avant moyenne. " +
      "Le signe détermine la direction (avec seuil 30 %), la magnitude alimente la 'Conviction OSINT'.",
    ref: 'ADR-004 + ADR-018',
  },
  dispersion: {
    term: 'Dispersion',
    short:
      "Écart-type des biais sentiment des sources non-outliers. Plus elle est faible, plus la veracity est haute.",
    long:
      "Mesure de la concordance entre les overlays sentiment du signal. " +
      "Dispersion ≤ 0.20 → veracity 0.95 (sources toutes alignées) ; " +
      "≤ 0.40 → 0.90 ; ≤ 0.60 → 0.85 ; ≤ 0.80 → 0.78 ; au-delà → 0.70. " +
      "Calculée sur les biais des sources non-outliers (les outliers AFN sont retirés du calcul).",
    ref: 'ADR-018',
  },
  outcome: {
    term: 'Outcome',
    short:
      "Résultat observé d'un signal suivi dans la Watchlist. pending, confirmed, refuted ou n_a.",
    long:
      "Vocabulaire OSINT-neutral hérité du pattern saved alerts (Recorded Future, Bloomberg). " +
      "pending = pas encore résolu ; confirmed = direction Tik validée par le marché ; refuted = direction Tik invalidée ; " +
      "n_a = data manquante ou non-applicable (weekend GOLD, etc.). " +
      "Le suffixe ✎ indique que l'utilisatrice a override manuellement l'outcome auto-calculé.",
    ref: 'Paquet 13 + 28',
  },
  evidence: {
    term: 'Evidence',
    short:
      "Preuves par source ayant alimenté le signal. Chaque preuve cite sa source, son score de crédibilité et son poids.",
    long:
      "Chaque overlay OSINT (et chaque indicateur technique informatif depuis ADR-018) ajoute une entrée 'evidence' au signal " +
      "contenant : source, fact (description), score (crédibilité 0.30-0.95), weight (poids dans le combined_bias), " +
      "et is_outlier (flag anti fake-news ADR-011). " +
      "C'est ce qui permet la transparence Tik (Paranoïa contrôlée).",
    ref: 'ADR-004 + ADR-011',
  },
  triggers: {
    term: 'Triggers',
    short:
      "Déclencheurs du signal, séparés par poids. Décisionnels (poids > 0) : sentiment OSINT en swing, microstructure en flash. Le contexte technique (RSI/MACD/EMA) ne déclenche PLUS rien (poids 0.0) depuis ADR-018.",
    long:
      "Depuis le refactor OSINT pur ADR-018, la direction vient UNIQUEMENT du combined_bias OSINT — pas de l'analyse technique. " +
      "La carte Triggers est donc séparée en deux : « Triggers décisionnels » (poids > 0, ce qui décide vraiment : les overlays sentiment OSINT en swing, la microstructure orderbook/agression en flash) " +
      "et « Contexte technique » (RSI 14, EMA 9/21, MACD 12/26/9, momentum, ATR — poids 0.0, purement informatif). " +
      "Les indicateurs techniques sont conservés pour que tu voies l'état du marché en complément, mais ils ne participent PAS à la décision directionnelle.",
    ref: 'ADR-018 + Paquet 36',
  },
  counterScenarios: {
    term: 'Counter-scenarios',
    short:
      "Au moins 2 scénarios qui invalideraient le signal, avec probabilité estimée et mitigation à surveiller.",
    long:
      "Cœur de la paranoïa contrôlée Tik (cf. CLAUDE.md section 6). Chaque signal livre ≥ 2 contre-scénarios " +
      "avec leur probabilité estimée et leur 'mitigation' (quoi surveiller pour le confirmer/infirmer). " +
      "C'est ce qui distingue Tik d'un bot naïf : on annonce la direction mais on documente explicitement comment elle pourrait se tromper.",
    ref: 'CLAUDE.md §6',
  },
  hypothesis: {
    term: 'Hypothèse',
    short:
      "Texte synthétique ~150 mots en 6 sections (verdict, technique, sentiment, AFN, risque, surveillance).",
    long:
      "Depuis ADR-012 (Paquet 6), l'hypothèse est synthétisée par LLM local (llama3.2:3b via Ollama) en 6 sections fixes : " +
      "Verdict, Lecture technique, Sentiment cross-validé, Anti fake-news, Risque principal, À surveiller. " +
      "Mode active depuis 2026-05-04 : Signal.hypothesis = sortie LLM, template historique conservé dans advisory.template_hypothesis pour audit. " +
      "Si Ollama down ou validation post-génération échoue (< 50 mots ou > 400) → fallback template automatique.",
    ref: 'ADR-012',
  },
  advisory: {
    term: 'Advisory',
    short:
      "Avis additionnels attachés au signal (warnings macro, candidate LLM, template d'audit, etc.).",
    long:
      "Dictionnaire libre d'avis additionnels : macro_crash_warning, bias_on_existing_positions, " +
      "llm_hypothesis_candidate (mode shadow ADR-012), template_hypothesis (audit mode active). " +
      "Lisible côté dashboard pour validation manuelle.",
    ref: 'Paquet 6',
  },
  sourceScores: {
    term: 'Source scores',
    short:
      "Crédibilité par source (0.30 à 0.95). FRED 0.85, Google News 0.70, Reddit 0.65, etc.",
    long:
      "Score de crédibilité affecté à chaque source OSINT, modulant son poids dans le combined_bias. " +
      "Sources gouvernementales chiffrées (FRED) 0.85 ; news scientifiques (GDELT) 0.75 ; mainstream éditorial (Google News, CryptoCompare) 0.70 ; " +
      "communautaire pondéré (Reddit) 0.65 ; sentiment numérique (Fear & Greed) 0.65 ; markets data (Binance klines) 0.90. " +
      "Recalibration automatique daily 03:00 UTC selon hit rate observé (ADR-011, fenêtre 30 jours).",
    ref: 'ADR-011',
  },
  gardeFou2bis: {
    term: 'Garde-fou 2-bis',
    short:
      "Règles strictes trading manuel J+24 : sizing 1 %, veracity ≥ 0.85 (transitoire), pas de GOLD, aucun edge directionnel prouvé.",
    long:
      "Règle opérationnelle pour le trading manuel J+24 (2026-05-24) : " +
      "(1) sizing 1 % du capital par trade pendant 2 semaines minimum, montée progressive seulement après période profitable mesurable ; " +
      "(2) filtre veracity ≥ 0.85 sur swing BTC transitoire tant que Reddit IP-bannie (au lieu de 0.90 normal) ; " +
      "(3) NE PAS trader GOLD avec Tik (aucun edge directionnel mesuré sur GOLD) ; " +
      "(4) AUCUN edge directionnel robuste démontré à ce jour — les chiffres antérieurs (SHORT BTC 63 %, GOLD 4,8 %) reposaient sur des données pré-fix contaminées (cf. CLAUDE.md Paquet 33). Ne pas s'en servir comme edge ; mesure fiable seulement au 2026-05-27 (swing 5j post-fix) ; " +
      "(5) discipline calendrier macro : ne pas entrer en swing dans les ±4h autour d'un event HIGH (FOMC, NFP, CPI).",
    ref: 'CLAUDE.md §5',
  },
  shadow: {
    term: 'Mode shadow',
    short:
      "Tik observe et logue sans jamais influencer les trades. 3 mois minimum avant connexion réelle Tik ↔ Zeta.",
    long:
      "Garde-fou 1 (CLAUDE.md §5). Tik tourne en parallèle de Zeta sans jamais influencer ses trades. " +
      "La connexion Zeta ne fait que LIRE (status, positions, PnL). Aucune influence sur les trades réels avant 3 mois minimum d'observation. " +
      "NE S'APPLIQUE PAS au trading manuel humain — c'est le jugement de l'utilisatrice qui filtre, pas un guard pipeline.",
    ref: 'Garde-fou 1',
  },
};

export const CRITICAL_TERMS = [
  'veracity',
  'conviction',
  'afn',
  'trackRecord',
  'horizon',
  'seuil',
] as const;

export function getEntry(key: string): GlossaryEntry | null {
  return GLOSSARY[key] ?? null;
}
