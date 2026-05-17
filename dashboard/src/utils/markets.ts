/**
 * Helpers liés aux horaires de marché.
 *
 * Marché GOLD spot (XAU/USD) : fenêtre forex standard, ouvre dimanche
 * 22h UTC, ferme vendredi 22h UTC. Yahoo Finance ne renvoie pas de
 * bougie en dehors de cette fenêtre → le track record ne peut pas
 * calculer de delta_pct et badge "données_manquantes".
 *
 * Cette fonction permet à l'UI d'afficher "marché fermé" au lieu d'un
 * libellé cryptique quand la cible d'un horizon tombe pendant la
 * fermeture week-end.
 *
 * BTC : marché 24/7, jamais fermé → la fonction n'est pas appelée
 * pour les signaux BTC.
 */
import { parseUtcIso } from './time';

export function isGoldMarketClosed(iso: string): boolean {
  const d = parseUtcIso(iso);
  const dow = d.getUTCDay(); // 0=dimanche, 5=vendredi, 6=samedi
  const hour = d.getUTCHours();

  // Samedi entier : marché fermé toute la journée
  if (dow === 6) return true;
  // Vendredi à partir de 22h UTC : fermeture hebdomadaire
  if (dow === 5 && hour >= 22) return true;
  // Dimanche avant 22h UTC : pas encore rouvert
  if (dow === 0 && hour < 22) return true;

  return false;
}
