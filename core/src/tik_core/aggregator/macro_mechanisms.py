"""Contenu ÉDUCATIF curé — mécanismes de transmission macro → actifs.

⚠ NATURE DE CE FICHIER : du **savoir général** (consensus macro mainstream),
PAS des données mesurées par Tik. C'est de la culture trading, hedgée, à
afficher SÉPARÉMENT des réactions réellement mesurées (BTC/OR) par Tik.

Pourquoi curé à la main (et pas généré par LLM) : la recherche 2026 montre que
les LLM finance fabriquent des faits « confidently » ; notre modèle local 3B est
faible. Du contenu curé, sourcé et hedgé = zéro hallucination, déterministe.

⚠ RÈGLE D'OR (régime-dépendance) : les liens intermarché sont des TENDANCES,
PAS des lois. Ils s'inversent selon le régime. Exemple vérifié 2024-2025 :
BTC et or ont été quasi DÉCORRÉLÉS (corrélation ≈ 0), donc « BTC monte donc l'or
chute » est FAUX comme règle. Chaque mécanisme porte donc un `regime_caveat`
affiché en toutes lettres. Sources : CryptoSlate / CME / ScienceDirect 2025.

Maintenance : contenu mainstream stable, mais à relire ~annuellement. Ne JAMAIS
présenter comme une vérité infaillible — c'est un cadre de lecture, pas une
prédiction. Les `event_code` correspondent à ceux de `macro_calendar_data`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MacroMechanism:
    """Fiche éducative d'un type d'event macro (savoir général, hedgé)."""

    event_code: str
    one_liner: str  # accroche punchy
    mechanism: str  # la chaîne causale, hedgée ("tend à", "souvent")
    assets_in_play: tuple[str, ...]  # actifs typiquement concernés (éducatif)
    regime_caveat: str  # avertissement régime-dépendance, toujours affiché


# Avertissement commun (régime-dépendance), réutilisé/spécialisé par event.
_REGIME = (
    "Ces liens sont des TENDANCES, pas des lois : ils dépendent du régime de "
    "marché et s'inversent. Ex. 2024-2025, BTC et or ont été quasi décorrélés "
    "(≈ 0) — « X monte donc Y chute » n'est PAS une règle fiable."
)

MECHANISMS: dict[str, MacroMechanism] = {
    "CPI": MacroMechanism(
        event_code="CPI",
        one_liner="Inflation conso : une surprise à la hausse = marché anticipe une Fed plus dure.",
        mechanism=(
            "Un CPI plus chaud que prévu pousse le marché à anticiper des taux Fed "
            "plus hauts/plus longtemps. Conséquences TYPIQUES : le dollar tend à se "
            "renforcer, ce qui pèse souvent sur l'or et le pétrole (cotés en dollars) "
            "et sur les actifs risqués (actions, crypto) ; les rendements obligataires "
            "montent. Un CPI plus froid joue dans l'autre sens (risk-on)."
        ),
        assets_in_play=("USD", "OR", "PÉTROLE", "ACTIONS/NASDAQ", "OBLIGATIONS", "BTC"),
        regime_caveat=_REGIME,
    ),
    "NFP": MacroMechanism(
        event_code="NFP",
        one_liner="Emploi US : un marché du travail tendu fait pression à la hausse sur les taux.",
        mechanism=(
            "Un NFP très supérieur aux attentes signale un emploi robuste → la Fed peut "
            "rester restrictive → dollar et rendements tendent à monter, pression sur "
            "l'or et les actifs risqués. Un NFP faible nourrit les anticipations de baisse "
            "de taux (risk-on). C'est l'un des chiffres les plus VOLATILS, et le sens est "
            "souvent contre-intuitif : selon ce que le marché redoute (inflation vs "
            "récession), un chiffre faible peut être salué… ou puni."
        ),
        assets_in_play=("USD", "OBLIGATIONS", "ACTIONS", "OR", "BTC"),
        regime_caveat=_REGIME,
    ),
    "FOMC_MEETING": MacroMechanism(
        event_code="FOMC_MEETING",
        one_liner="Décision Fed : la décision de taux, mais surtout le TON (hawkish/dovish).",
        mechanism=(
            "La décision de taux et SURTOUT le ton (conférence, projections « dot plot ») "
            "orientent tout. Un ton restrictif (hawkish) → dollar et rendements montent, "
            "pression sur or, actions et crypto ; un ton accommodant (dovish) → risk-on. "
            "Le marché réagit souvent plus au TON qu'à la décision elle-même, qui est "
            "fréquemment déjà anticipée (price-in)."
        ),
        assets_in_play=("USD", "OBLIGATIONS", "ACTIONS", "OR", "BTC", "PÉTROLE"),
        regime_caveat=_REGIME,
    ),
    "PPI": MacroMechanism(
        event_code="PPI",
        one_liner="Prix producteurs : un précurseur de l'inflation conso (CPI).",
        mechanism=(
            "Le PPI mesure les prix en amont (producteurs) ; il préfigure souvent le CPI. "
            "Une surprise à la hausse ravive les craintes inflationnistes (mécanique "
            "proche du CPI : dollar et rendements tendent à monter, pression sur or et "
            "actifs risqués). Impact généralement plus modéré que le CPI."
        ),
        assets_in_play=("USD", "OBLIGATIONS", "OR", "ACTIONS", "BTC"),
        regime_caveat=_REGIME,
    ),
    "GDP": MacroMechanism(
        event_code="GDP",
        one_liner="Croissance US : double lecture (santé de l'économie vs craintes d'inflation).",
        mechanism=(
            "Un PIB fort = économie solide : généralement risk-on (actions tendent à "
            "monter). MAIS s'il ravive les craintes d'inflation/taux, le dollar peut "
            "monter et peser sur l'or. Un PIB faible = craintes de ralentissement "
            "(risk-off), qui peut aussi nourrir l'espoir de baisses de taux. La réaction "
            "dépend donc de ce que le marché priorise sur le moment."
        ),
        assets_in_play=("ACTIONS", "USD", "OR", "BTC", "PÉTROLE"),
        regime_caveat=_REGIME,
    ),
    "RETAIL_SALES": MacroMechanism(
        event_code="RETAIL_SALES",
        one_liner="Consommation US (~70 % du PIB) : santé de la demande domestique.",
        mechanism=(
            "Retail Sales mesurent la dépense des ménages US. Un chiffre fort signale "
            "une consommation résiliente : économie OK mais pression à la hausse sur "
            "l'inflation → la Fed peut rester restrictive plus longtemps → dollar et "
            "rendements tendent à monter, pression sur or et actifs risqués. Un chiffre "
            "faible nourrit les anticipations de ralentissement (risk-off) ou de baisses "
            "de taux (risk-on) — la lecture dépend de ce que le marché priorise. Impact "
            "généralement moindre que CPI/NFP mais souvent suiveur le mois d'après."
        ),
        assets_in_play=("USD", "ACTIONS", "OR", "OBLIGATIONS", "BTC"),
        regime_caveat=_REGIME,
    ),
    "INDUSTRIAL_PRODUCTION": MacroMechanism(
        event_code="INDUSTRIAL_PRODUCTION",
        one_liner="Production industrielle US : indicateur cyclique (souvent peu market-moving).",
        mechanism=(
            "L'IP mesure l'output des usines, mines et utilities US. Une publication "
            "forte signale une économie cyclique en expansion → tend à soutenir le "
            "dollar et les secteurs cycliques (matières premières demandées : pétrole, "
            "cuivre). Une publication faible signale un ralentissement industriel, "
            "parfois précurseur de récession. Impact généralement contenu : les PMI "
            "publiés en amont anticipent déjà partiellement le chiffre."
        ),
        assets_in_play=("USD", "ACTIONS", "PÉTROLE", "MATIÈRES PREMIÈRES", "OR"),
        regime_caveat=_REGIME,
    ),
    "INITIAL_CLAIMS": MacroMechanism(
        event_code="INITIAL_CLAIMS",
        one_liner="Inscriptions hebdo au chômage US : baromètre haute fréquence du marché du travail.",
        mechanism=(
            "Les Initial Claims mesurent les nouvelles demandes d'allocations chômage "
            "(données hebdo, donc volatiles). Une hausse signale un marché du travail "
            "qui faiblit → anticipations de Fed dovish → dollar tend à baisser, taux "
            "longs aussi, actions souvent positives (« bad news = good news »). Une "
            "baisse signale un emploi tendu → Fed potentiellement plus dure → dollar "
            "ferme. Un chiffre isolé bouge peu le marché : c'est la MOYENNE 4 semaines "
            "et la TENDANCE qui comptent."
        ),
        assets_in_play=("USD", "ACTIONS", "OBLIGATIONS", "OR", "BTC"),
        regime_caveat=_REGIME,
    ),
    "ECB_GOVERNING_COUNCIL": MacroMechanism(
        event_code="ECB_GOVERNING_COUNCIL",
        one_liner="Décision BCE : taux zone euro + ton Lagarde (équivalent européen du FOMC).",
        mechanism=(
            "Le Conseil des gouverneurs BCE fixe les taux de la zone euro. Un ton "
            "restrictif (hawkish) ou une décision plus dure qu'attendue → l'euro tend à "
            "monter contre le dollar (EUR/USD ↑), les rendements souverains européens "
            "montent, pression sur actions européennes et indirectement sur l'or "
            "(taux réels). Un ton accommodant joue dans l'autre sens. L'effet est "
            "amplifié par l'ÉCART de politique avec la Fed plutôt que par les niveaux "
            "absolus — la BCE étant souvent en retard de phase. Impact sur BTC indirect "
            "(via dollar et risk-on global)."
        ),
        assets_in_play=("EUR/USD", "ACTIONS EU", "OBLIGATIONS EU", "OR", "BTC"),
        regime_caveat=_REGIME,
    ),
    "BOJ_MPM": MacroMechanism(
        event_code="BOJ_MPM",
        one_liner="BoJ (Banque du Japon) : pilotage du yen + normalisation post-NIRP.",
        mechanism=(
            "La BoJ pilote le yen via taux et politique de contrôle de courbe (YCC). "
            "Depuis 2024 elle est sortie progressivement du Negative Interest Rate "
            "Policy → toute hausse/normalisation supplémentaire renforce le JPY contre "
            "le dollar (USD/JPY ↓). Effet collatéral majeur : peut déclencher un "
            "« unwind » du carry trade JPY global (positions risquées financées en yen) "
            "→ actions/crypto sous pression (épisode août 2024 = exemple récent). Un "
            "ton dovish (maintien) laisse le carry trade vivre → risk-on global. La "
            "BoJ est l'événement le MOINS prévisible des grandes banques centrales."
        ),
        assets_in_play=("USD/JPY", "ACTIONS GLOBALES", "ACTIONS JP", "BTC", "OR"),
        regime_caveat=_REGIME,
    ),
    "BOE_MPC": MacroMechanism(
        event_code="BOE_MPC",
        one_liner="BoE (Banque d'Angleterre) : taux UK + ton Bailey (effet souvent contenu hors UK).",
        mechanism=(
            "Le MPC de la BoE fixe les taux UK. Un ton restrictif tend à renforcer la "
            "livre (GBP/USD ↑), pousser les rendements souverains UK vers le haut et "
            "peser sur le FTSE et les actions UK. Un ton dovish joue dans l'autre sens. "
            "L'effet sur or et BTC reste essentiellement indirect (via dollar et "
            "risk-on global). La sterling est aussi très sensible à la politique "
            "intérieure UK (budget, politique fiscale) — un signal BoE peut être "
            "neutralisé par un facteur domestique le même jour."
        ),
        assets_in_play=("GBP/USD", "ACTIONS UK", "OBLIGATIONS UK", "OR", "BTC"),
        regime_caveat=_REGIME,
    ),
}


# Fiche générique pour un event sans mécanisme curé (on n'invente pas un
# mécanisme spécifique : on rappelle le canal général + le caveat).
GENERIC_MECHANISM = MacroMechanism(
    event_code="GENERIC",
    one_liner="Donnée macro US : impact via les anticipations de taux et le dollar.",
    mechanism=(
        "Une surprise sur cette donnée modifie les anticipations de politique monétaire "
        "(taux Fed) et de croissance, ce qui se transmet d'abord au dollar et aux "
        "rendements obligataires, puis à l'or, au pétrole et aux actifs risqués (actions, "
        "crypto). L'ampleur et le sens dépendent fortement de l'écart au consensus."
    ),
    assets_in_play=("USD", "OBLIGATIONS", "OR", "ACTIONS", "BTC"),
    regime_caveat=_REGIME,
)


def get_mechanism(event_code: str) -> MacroMechanism:
    """Mécanisme curé pour un event_code, ou la fiche générique en repli."""
    return MECHANISMS.get(event_code, GENERIC_MECHANISM)
