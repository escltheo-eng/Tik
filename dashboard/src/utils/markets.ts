/**
 * Helpers liés aux horaires de marché.
 *
 * Marché GOLD (`GC=F` futures via Yahoo Finance) : fenêtre forex standard,
 * ouvre dimanche 22h UTC, ferme vendredi 22h UTC, ET fermé les jours fériés
 * US majeurs (Memorial Day, Thanksgiving, Noël…). Yahoo ne renvoie aucune
 * bougie en dehors de ces fenêtres → le track record ne peut pas calculer de
 * delta_pct et tombe en badge "données_manquantes". Cause structurelle, pas
 * un bug Tik.
 *
 * Cette fonction permet à l'UI d'afficher "marché fermé" au lieu d'un libellé
 * cryptique "données non disponibles" quand la cible d'un horizon tombe
 * pendant une fermeture (week-end OU jour férié).
 *
 * BTC : marché 24/7, jamais fermé → ces fonctions ne sont pas appelées pour
 * les signaux BTC.
 */
import { parseUtcIso } from './time';

/**
 * Jours fériés US majeurs où le marché de l'or (COMEX/CME `GC=F`) est fermé
 * (ou en early-close) et où Yahoo Finance ne fournit pas de bougie intraday.
 * Clé = date US 'YYYY-MM-DD', valeur = libellé FR affiché.
 *
 * ⚠ Best-effort, mise à jour annuelle manuelle (même logique que les dates
 * FOMC/ECB hardcodées côté backend dans macro_calendar_data.py). Le critère
 * retenu = "Yahoo ne renvoie pas de prix GC=F ce jour-là" → on liste les
 * fermetures pleines NYSE/CME. Certaines fêtes sont des early-close côté
 * métaux et les futures rouvrent le dimanche soir, mais pour l'affichage du
 * track record ça reste suffisant. Source : calendriers officiels NYSE/CME.
 */
export const US_MARKET_HOLIDAYS: Record<string, string> = {
  // 2026
  '2026-01-01': "Jour de l'an",
  '2026-01-19': 'Martin Luther King Jr. Day',
  '2026-02-16': 'Presidents Day',
  '2026-04-03': 'Vendredi saint',
  '2026-05-25': 'Memorial Day',
  '2026-06-19': 'Juneteenth',
  '2026-07-03': 'Independence Day (observé)',
  '2026-09-07': 'Labor Day',
  '2026-11-26': 'Thanksgiving',
  '2026-12-25': 'Noël',
  // 2027 (estimations sur le pattern habituel — à confirmer fin 2026)
  '2027-01-01': "Jour de l'an",
  '2027-01-18': 'Martin Luther King Jr. Day',
  '2027-02-15': 'Presidents Day',
  '2027-03-26': 'Vendredi saint',
  '2027-05-31': 'Memorial Day',
  '2027-06-18': 'Juneteenth (observé)',
  '2027-07-05': 'Independence Day (observé)',
  '2027-09-06': 'Labor Day',
  '2027-11-25': 'Thanksgiving',
  '2027-12-24': 'Noël (observé)',
};

/** Clé 'YYYY-MM-DD' (en UTC) d'une Date — pour le lookup jours fériés. */
function utcDateKey(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** Nom du jour férié US si `d` tombe un jour férié marché (date UTC), sinon null. */
export function usMarketHolidayName(d: Date): string | null {
  return US_MARKET_HOLIDAYS[utcDateKey(d)] ?? null;
}

export function isGoldMarketClosed(iso: string): boolean {
  const d = parseUtcIso(iso);
  const dow = d.getUTCDay(); // 0=dimanche, 5=vendredi, 6=samedi
  const hour = d.getUTCHours();

  // Jour férié US : marché de l'or fermé, Yahoo sans données.
  if (usMarketHolidayName(d) !== null) return true;

  // Samedi entier : marché fermé toute la journée
  if (dow === 6) return true;
  // Vendredi à partir de 22h UTC : fermeture hebdomadaire
  if (dow === 5 && hour >= 22) return true;
  // Dimanche avant 22h UTC : pas encore rouvert
  if (dow === 0 && hour < 22) return true;

  return false;
}

export interface GoldClosureNotice {
  /** Libellé prêt à afficher, ex: "Marché de l'or fermé aujourd'hui — Memorial Day". */
  label: string;
  /** true si la fermeture est en cours maintenant, false si elle est à venir. */
  closedNow: boolean;
}

/**
 * Notice de fermeture du marché de l'or pour le calendrier macro.
 *
 * Priorité :
 *   1. Fermé maintenant pour jour férié → notice "fermé aujourd'hui — <fête>".
 *   2. Fermé maintenant pour le week-end → notice "fermé ce week-end".
 *   3. Jour férié à venir dans `windowDays` → notice d'anticipation.
 *   4. Sinon null (marché ouvert, rien à signaler).
 *
 * Pure (prend `now` en paramètre) → testable sans mock d'horloge.
 */
export function goldClosureNotice(now: Date, windowDays = 7): GoldClosureNotice | null {
  const holidayToday = usMarketHolidayName(now);
  if (holidayToday !== null) {
    return {
      label: `Marché de l'or fermé aujourd'hui — ${holidayToday}`,
      closedNow: true,
    };
  }

  const dow = now.getUTCDay();
  const hour = now.getUTCHours();
  const weekendNow = dow === 6 || (dow === 5 && hour >= 22) || (dow === 0 && hour < 22);
  if (weekendNow) {
    return {
      label: "Marché de l'or fermé ce week-end (reprise dim. 22h UTC)",
      closedNow: true,
    };
  }

  // Anticipation : prochain jour férié dans la fenêtre (jours suivants).
  for (let i = 1; i <= windowDays; i++) {
    const d = new Date(now.getTime() + i * 86400_000);
    const name = usMarketHolidayName(d);
    if (name !== null) {
      const dd = String(d.getUTCDate()).padStart(2, '0');
      const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
      return {
        label: `Marché de l'or fermé le ${dd}/${mm} — ${name}`,
        closedNow: false,
      };
    }
  }

  return null;
}
