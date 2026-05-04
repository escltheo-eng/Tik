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

export function parseUtcIso(iso: string): Date {
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
