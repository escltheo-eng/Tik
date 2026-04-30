# Backlog Tik — améliorations différées

> Ce fichier liste les pistes identifiées mais non implémentées tout de suite.
> Chaque entrée explique le contexte et le coût/bénéfice estimé.

---

## 1. Renforcer le keyword classifier (fallback Ollama)

**Date d'identification** : 2026-04-30

**Contexte** : suite à l'intégration d'Ollama (`llama3.2:3b`) comme premier
classifier de sentiment news, le `KeywordClassifier` devient un mode dégradé
utilisé uniquement quand Ollama est indisponible (cf. `news_classifier.py`).
Une suggestion d'enrichissement des listes a été analysée puis écartée pour
le bloc principal car la majorité des cas (négation, polarité contextuelle,
multi-mots) sont déjà couverts par construction par le LLM.

### 1.A — Ajouter ~8 mots-clés mono-mot non ambigus

À ajouter dans `news_classifier.py:BULLISH_KEYWORDS` :

- `reclaim`, `reclaims`, `reclaimed` *(ex : "BTC reclaims 100k")*

À ajouter dans `news_classifier.py:BEARISH_KEYWORDS` :

- `topping` *(formation de sommet)*
- `rejection` *(rejet d'un niveau de résistance)*
- `breakdown` *(cassure baissière de support)*
- `outflows` *(sorties de capitaux ETF/exchange)*
- `unloading` *(distribution agressive)*

**Coût estimé** : 5 minutes (ajout listes + 1-2 tests paramétrés).

**Bénéfice** : marginal (le fallback est rare, déclenché seulement quand
Ollama est down ou que son circuit breaker batch est ouvert). Mais le coût
est si faible que ça reste rentable.

**Mots écartés volontairement** car ambigus mono-mot :

- `inflows` (bull pour ETF, bear pour "miner inflows to exchanges")
- `distribution` (bull "wide distribution" vs bear "smart money distribution")
- `consolidation`, `expansion`, `absorption`, `volatility`, `correction`
  (tous interprétables dans les deux sens selon le contexte)
- `fear`, `risk`, `capitulation` (déjà flaggés ambigus, ne pas étendre)

**Mots multi-mots à NE PAS implémenter côté keywords** : tout ce qui demande
n-grammes (`higher low`, `losing support`, `failed breakout`, `panic selling`,
`fear spike`, `risk off`, etc.). Ces cas sont précisément le rôle d'Ollama.

### 1.B — Dataset golden pour benchmark quantitatif

L'angle vraiment utile à terme. Créer `core/tests/data/golden_titles.json`
avec ~50 titres réels annotés manuellement (BULLISH / BEARISH / NEUTRAL),
incluant :

- Les cas clairs (sanity check)
- Les cas pièges multi-mots (`Bitcoin holding support` vs `losing support`)
- Les cas avec polarité contextuelle (`fear has eased, traders resume buying`)
- Les cas techniques précis (`higher low forming`, `lower high rejected`)

Puis un test paramétré qui lance `KeywordClassifier` ET `OllamaClassifier`
sur le dataset, avec rapport comparatif (accuracy, precision, recall par
classe). C'est ce qui permettra de **mesurer** objectivement le gain
Ollama vs keywords plutôt que de débattre.

**Coût estimé** : 1-2 h (sélection + annotation manuelle + script de
benchmark). À déclencher quand Ollama aura tourné 2-3 semaines pour
collecter des cas réels intéressants depuis les logs.

**Lié au backtest existant** : le ingester loggue déjà
`method=ollama:llama3.2:3b` ou `method=keywords` dans Redis pour chaque
publication, donc le backtest pourra aussi comparer le hit rate par méthode
sur les vrais signaux Tik.
