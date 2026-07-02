/**
 * Helpers temps — gestion des timestamps ISO renvoyés par le core.
 *
 * Le core émet aujourd'hui ses timestamps via `datetime.utcnow()` (Pydantic
 * sérialise sans suffixe `Z`). JavaScript interprète une chaîne ISO sans
 * timezone comme heure locale, ce qui crée un décalage de +UTC offset
 * entre l'âge réel d'un signal et son affichage. `parseUtcIso` force
 * l'interprétation en UTC en ajoutant `Z` si absent.
 *
 * Si le core ajoute un jour la timezone explicite (`...Z` ou `+00:00`),
 * `parseUtcIso` le détecte et n'ajoute rien — donc compatible.
 */

const TZ_SUFFIX_RE = /[Zz]|[+\-]\d{2}:?\d{2}$/;
// Date seule "YYYY-MM-DD" (sans heure) : le core renvoie ça pour les données
// macro journalières/hebdo (FRED, DefiLlama…). On la traite comme minuit UTC,
// sinon `${iso}Z` donne "2026-06-25Z" = Date invalide → "il y a NaN".
const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/;

export function parseUtcIso(iso: string): Date {
  if (DATE_ONLY_RE.test(iso)) return new Date(`${iso}T00:00:00Z`);
  const normalized = TZ_SUFFIX_RE.test(iso) ? iso : `${iso}Z`;
  return new Date(normalized);
}

export function timeAgo(iso: string): string {
  const then = parseUtcIso(iso).getTime();
  const now = Date.now();
  const diffMs = Math.max(0, now - then);
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `il y a ${sec} s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `il y a ${min} min`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `il y a ${hours} h`;
  const days = Math.floor(hours / 24);
  return `il y a ${days} j`;
}

export function formatLocal(iso: string): string {
  return parseUtcIso(iso).toLocaleString();
}

/**
 * Compte à rebours pour un instant futur (ex: "dans 4 j 22 h", "dans 3 h").
 *
 * Utilisé par la carte calendrier macro (Lacune B Phase B1 J+10) pour
 * afficher "FOMC dans 4 j 22 h" sur le next event.
 *
 * Si l'instant est passé, retourne "imminent" (≤ 0 s).
 */
export function timeUntil(iso: string): string {
  const then = parseUtcIso(iso).getTime();
  const now = Date.now();
  const diffMs = then - now;
  if (diffMs <= 0) return 'imminent';
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `dans ${sec} s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `dans ${min} min`;
  const hours = Math.floor(min / 60);
  if (hours < 24) {
    const remainingMin = min - hours * 60;
    if (remainingMin === 0 || hours >= 6) return `dans ${hours} h`;
    return `dans ${hours} h ${remainingMin} min`;
  }
  const days = Math.floor(hours / 24);
  const remainingHours = hours - days * 24;
  if (remainingHours === 0 || days >= 7) return `dans ${days} j`;
  return `dans ${days} j ${remainingHours} h`;
}
