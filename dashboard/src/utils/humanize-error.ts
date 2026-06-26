/**
 * humanizeError — traduit une erreur du client HTTP en un message FR métier,
 * lisible par une non-technicienne. JAMAIS de dump technique brut affiché
 * (« 401 Forbidden {…} », « timeout (10000ms) on … »).
 *
 * Pourquoi `unknown` en entrée : les cartes reçoivent souvent l'erreur déjà
 * aplatie en string (`err.message`), parfois l'objet `Error`. On gère les deux :
 *  - si on a la classe Tik (AuthError, NetworkError…) → on l'utilise (fiable) ;
 *  - sinon → heuristiques regex sur le texte (quand la classe est perdue en route).
 *
 * Contrat des 4 états (CLAUDE.md §13ter) : ce helper sert l'état « Erreur ».
 */
import { AuthError, NetworkError, NotFoundError, ServerError } from '@/src/api/errors';

const MSG_AUTH = 'Clé API refusée ou sans les droits (vérifie ou renouvelle la clé).';
const MSG_NETWORK = "Serveur injoignable (vérifie la connexion et l'adresse du core).";
const MSG_NOTFOUND = 'Donnée introuvable (peut-être expirée).';
const MSG_SERVER = 'Erreur côté serveur — réessaie dans un moment.';
const MSG_GENERIC = 'Indisponible pour le moment.';

export function humanizeError(input: unknown): string {
  // 1) La classe d'erreur Tik est la source la plus fiable.
  if (input instanceof AuthError) return MSG_AUTH;
  if (input instanceof NetworkError) return MSG_NETWORK;
  if (input instanceof NotFoundError) return MSG_NOTFOUND;
  if (input instanceof ServerError) return MSG_SERVER;

  // 2) Sinon on récupère un texte (string passée par une carte, ou Error.message).
  const raw =
    typeof input === 'string'
      ? input
      : input instanceof Error
        ? input.message
        : input == null
          ? ''
          : String(input);
  const s = raw.toLowerCase();
  if (!s) return MSG_GENERIC;

  // 3) Heuristiques sur le texte brut.
  if (/\b401\b|\b403\b|forbidden|unauthorized|missing scope|\bauth\b/.test(s)) return MSG_AUTH;
  if (/timeout|network|injoignable|failed to fetch|econn|fetch failed|aborted?/.test(s))
    return MSG_NETWORK;
  if (/\b404\b|not found|introuvable/.test(s)) return MSG_NOTFOUND;
  if (/\b5\d\d\b|server error|internal/.test(s)) return MSG_SERVER;
  return MSG_GENERIC;
}
